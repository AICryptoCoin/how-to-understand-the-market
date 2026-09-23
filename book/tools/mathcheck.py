"""Детектор сломанных формул.

Заведён 2026-09-23 после главы 10, где 63 управляющих символа и две оборванные
команды прошли все три прибора приёмки и обе половины двойной приёмки.

Откуда берётся поломка. Главу собирал скрипт на Python обычными строками, и
последовательности вида `\\t`, `\\b`, `\\f`, `\\a`, `\\r` в формулах были
истолкованы как управляющие символы: `\\text{` превращалось в TAB + `ext{`,
`\\frac{` — в FORMFEED + `rac{`, `\\right)` — в CR + `ight)`.

Почему счёта управляющих байтов НЕ ХВАТАЕТ. Пять из семи опасных символов
(BEL, BS, TAB, VT, FF) видны счётом. Два — CR и LF — в файле с концами строк
CRLF неотличимы от обычного перевода строки: счётчик показывает идеальный ноль
при живом дефекте. Поэтому здесь три независимых способа, и третий ловит
именно этот случай:

1. счёт управляющих байтов;
2. оборванный хвост команды внутри формулы (`ight)` там, где был `\\right)`);
3. баланс парных конструкций `\\left`/`\\right` и разделителей формул.

Модуль отдельный и самостоятельный: его можно прогнать по любому файлу
напрямую, `python tools/mathcheck.py <файл>`, и он же вызывается из audit.py.
"""

import re
import sys
from pathlib import Path

BS = chr(92)

# Управляющие байты, в которые превращаются съеденные escape-последовательности.
#
# Разделены намеренно. BEL, BS, VT, FF в честной вёрстке не встречаются никогда,
# поэтому ищутся по всему файлу. TAB — обычный отступ HTML, и счёт его по всему
# файлу дал бы ложную тревогу на любой главе с табами; поэтому он ищется
# только внутри формул, где ему взяться неоткуда.
CTRL_ANYWHERE = {7: "a", 8: "b", 11: "v", 12: "f"}
CTRL_IN_MATH = {9: "t"}

# Хвосты команд LaTeX, первая буква которых совпадает с escape-символом Python
# и потому может быть съедена. Пара: (что осталось, что было).
TAILS = [
    ("ight)", "right)"),
    ("ight]", "right]"),
    ("ight|", "right|"),
    ("ight.", "right."),
    ("ext{", "text{"),
    ("extbf{", "textbf{"),
    ("extit{", "textit{"),
    ("ar{", "bar{"),
    ("rac{", "frac{"),
    ("ho_", "rho_"),
    ("ho}", "rho}"),
    ("au_", "tau_"),
    ("heta", "theta"),
    ("lpha", "alpha"),
    ("eta_", "beta_"),
    ("pprox", "approx"),
    ("imes", "times"),
]

# Области формул: \( … \), \[ … \], $$ … $$
REGION = re.compile(
    re.escape(BS + "(") + r"(.*?)" + re.escape(BS + ")")
    + r"|" + re.escape(BS + "[") + r"(.*?)" + re.escape(BS + "]")
    + r"|" + r"\$\$(.*?)\$\$",
    re.S,
)

# Парные конструкции: имя команды без ведущего слэша.
PAIRS = [("left", "right")]


def _line_of(raw, pos):
    return raw.count("\n", 0, pos) + 1


def check(raw: str) -> list:
    """Список поломок формул. Пустой список — поломок нет."""
    out = []

    # 1. Управляющие байты, которых в вёрстке не бывает вовсе.
    for code in sorted(CTRL_ANYWHERE):
        n = raw.count(chr(code))
        if n:
            out.append("управляющий байт %d: %d (съеден %s%s)"
                       % (code, n, BS, CTRL_ANYWHERE[code]))

    # 2. Оборванные хвосты команд и TAB — только внутри формул.
    #    Хвост ищем там, где он не является частью слова и перед ним нет
    #    обратного слэша: иначе `\text{` считался бы собственной поломкой.
    for m in REGION.finditer(raw):
        body = next(g for g in m.groups() if g is not None)
        for code in sorted(CTRL_IN_MATH):
            n = body.count(chr(code))
            if n:
                out.append("управляющий байт %d внутри формулы: %d (съеден %s%s), строка %d"
                           % (code, n, BS, CTRL_IN_MATH[code], _line_of(raw, m.start())))
        for tail, was in TAILS:
            pat = r"(?<![A-Za-z" + re.escape(BS) + r"])" + re.escape(tail)
            for _ in re.finditer(pat, body):
                out.append("оборванная команда %r (был %s%s), строка %d"
                           % (tail, BS, was, _line_of(raw, m.start())))

    # 3. Баланс парных конструкций — ВНУТРИ каждой формулы, а не по файлу.
    #    По файлу считать нельзя: любое упоминание \right в прозе или в
    #    комментарии вёрстки уравновешивает счёт и прячет дефект. Проверено:
    #    именно так эталон broken.html сначала показал ноль вместо поломки.
    for m in REGION.finditer(raw):
        body = next(g for g in m.groups() if g is not None)
        for a, b in PAIRS:
            na = len(re.findall(re.escape(BS + a) + r"(?![A-Za-z])", body))
            nb = len(re.findall(re.escape(BS + b) + r"(?![A-Za-z])", body))
            if na != nb:
                out.append("непарные %s%s/%s%s внутри формулы: %d против %d, строка %d"
                           % (BS, a, BS, b, na, nb, _line_of(raw, m.start())))

    for op, cl in ((BS + "(", BS + ")"), (BS + "[", BS + "]")):
        na = raw.count(op)
        nb = raw.count(cl)
        if na != nb:
            out.append("непарные %s/%s: %d против %d" % (op, cl, na, nb))

    if raw.count("$$") % 2:
        out.append("непарные $$: %d" % raw.count("$$"))

    return out


def main(argv) -> int:
    if len(argv) < 2:
        print("использование: python tools/mathcheck.py <файл.html> [ещё файлы]")
        return 64
    bad = 0
    for name in argv[1:]:
        p = Path(name)
        if not p.exists():
            print("НЕТ ФАЙЛА: %s" % name)
            bad += 1
            continue
        problems = check(p.read_text(encoding="utf-8"))
        print("%s: поломок %d" % (p.name, len(problems)))
        for line in problems:
            print("   %s" % line)
        bad += len(problems)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
