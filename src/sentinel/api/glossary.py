"""Plain-English labels for every code and term the lookup shows (feature 005, R6; rule P7).

Transaction codes follow the SEC's Form 4 General Instructions, item 8. Each entry is
(short label, longer explanation): pages show the label beside the code, and the glossary shows
both. A code is never displayed without its label.
"""

CODES: dict[str, tuple[str, str]] = {
    "P": ("Bought shares on the open market or privately",
          "An open-market or private purchase: the insider paid for the shares. The study's "
          "events are built only from these, after further checks."),
    "S": ("Sold shares on the open market or privately",
          "An open-market or private sale."),
    "V": ("Reported voluntarily, earlier than required",
          "A trade the insider chose to report before the deadline."),
    "A": ("Received shares from the company (award or grant)",
          "A grant, award or other acquisition from the company, usually part of pay."),
    "D": ("Returned or sold shares to the company",
          "A disposal of shares back to the company."),
    "F": ("Gave up shares to pay tax or an exercise price",
          "Shares delivered or withheld to pay the exercise price of an option, or the tax due "
          "when shares vest or options are exercised."),
    "I": ("Discretionary trade under a company plan",
          "A discretionary transaction under a company benefit plan, such as a switch between "
          "funds that buys or sells company shares."),
    "M": ("Exercised options (or converted a derivative)",
          "The exercise or conversion of an option or other derivative under a company plan."),
    "C": ("Converted a derivative into shares",
          "The conversion of a derivative security, such as convertible preferred stock."),
    "E": ("A short derivative position expired",
          "The expiry of a short position in an option or other derivative."),
    "H": ("A derivative expired or was cancelled, with value received",
          "The expiry or cancellation of a long derivative position, for which value was "
          "received."),
    "O": ("Exercised an out-of-the-money option",
          "The exercise of an option whose exercise price was above the market price."),
    "X": ("Exercised an in-the-money option",
          "The exercise of an option whose exercise price was at or below the market price."),
    "G": ("Gave or received shares as a gift",
          "A genuine gift of shares, given or received."),
    "L": ("Small acquisition",
          "A small acquisition that the SEC's Rule 16a-6 allows to be reported later."),
    "W": ("Inherited or passed on shares",
          "Shares acquired or disposed of by will or inheritance."),
    "Z": ("Moved shares into or out of a voting trust",
          "A deposit into, or withdrawal from, a voting trust."),
    "J": ("Other acquisition or disposition (see the footnote)",
          "A transaction that fits no other code; the filer explains it in a footnote."),
    "K": ("Equity swap or similar contract",
          "A transaction in an equity swap or a contract that works like one."),
    "U": ("Shares tendered in a takeover",
          "Shares given up in a tender offer during a change of control."),
}  # fmt: skip
BLANK_CODE = "No code reported"

FORMS: dict[str, tuple[str, str]] = {
    "3": ("Initial statement of holdings",
          "Filed when someone becomes an insider, listing what they own. It reports no trade."),
    "4": ("Report of a change in holdings",
          "Filed within two business days of a trade by an insider."),
    "5": ("Annual catch-up report",
          "Filed after the company's year end for small or exempt trades not reported on Form 4."),
    "3/A": ("Correction of a Form 3", "An amendment to an earlier Form 3."),
    "4/A": ("Correction of a Form 4",
            "An amendment to an earlier Form 4. It can repeat trades already reported."),
    "5/A": ("Correction of a Form 5", "An amendment to an earlier Form 5."),
}  # fmt: skip

ROLES: dict[str, tuple[str, str]] = {
    "ceo_cfo": ("CEO or CFO",
                "An officer whose title names the chief executive or chief financial officer."),
    "officer": ("Officer", "An executive of the company other than the CEO or CFO."),
    "director": ("Director", "A member of the company's board."),
    "ten_pct": ("Owner of more than 10%",
                "A person or fund owning more than 10% of a class of the company's shares."),
    "other": ("Other insider", "Another reporting person, or no role given on the filing."),
}  # fmt: skip

HOLDINGS: dict[str, tuple[str, str]] = {
    "D": ("Held directly", "Shares held in the insider's own name."),
    "I": ("Held indirectly",
          "Shares held through a trust, a family member, a company or a fund; the filing names "
          "the holder."),
}  # fmt: skip

ACQ_DISP: dict[str, str] = {"A": "Acquired", "D": "Disposed of"}

EVENT_KINDS: dict[str, tuple[str, str]] = {
    "A": ("Cluster",
          "Two or more separate insiders, at least one an officer or director, bought on the open "
          "market within 14 days, for $100,000 or more in total."),
    "B1": ("CEO or CFO buying alone",
           "The CEO or CFO bought $100,000 or more within 14 days, and no other insider bought."),
    "B2": ("Officer or director buying alone",
           "Another officer, or a director, bought $100,000 or more within 14 days, and no other "
           "insider bought."),
}  # fmt: skip
EVENT_RULES = (
    "Only genuine open-market purchases of common stock count: no awards, pre-planned trades, "
    "purchases in the company's own share sales, late reports, or filings under $25,000. People "
    "and funds that file together count as one buyer."
)

TERMS: dict[str, str] = {
    "Insider": "A company's officers, its directors, and anyone owning more than 10% of a class "
               "of its shares. US law makes them report their trades in the company's stock.",
    "Form 4": "The report an insider files with the SEC within two business days of a trade.",
    "CIK": "The SEC's permanent ID number for a company or a person. Tickers change; CIKs do not.",
    "Accession number": "The unique ID of one filing on EDGAR, the SEC's filing system.",
    "Trade date and filing date": "The day of the trade, and the day the SEC received the "
                                  "report. The filing date is when the trade became public.",
    "Reported price": "The price per share written on the filing by the insider. It is shown as "
                      "filed and can contain errors; it is often an average of several fills.",
    "Shares held afterwards": "How many shares the insider held after the trade, in that "
                              "holding (directly, or in one trust or fund).",
    "Signal date": "The filing date of the report that completed an insider-buying event.",
    "Data as of": "The newest filing date in the data, and the SEC quarterly data set it comes "
                  "from. Filings made after that date are not shown yet.",
}  # fmt: skip


def describe_code(code: str | None) -> str:
    """The short label for a transaction code; never the bare code."""
    if code is None or not code.strip():
        return BLANK_CODE
    entry = CODES.get(code.strip().upper())
    return entry[0] if entry else f"Code “{code}” (not described by the SEC)"


def label(table: dict, key: str | None, default: str = "Not reported") -> str:
    """The short label of `key` in one of the tables above."""
    entry = table.get(key) if key is not None else None
    if entry is None:
        return default
    return entry[0] if isinstance(entry, tuple) else entry
