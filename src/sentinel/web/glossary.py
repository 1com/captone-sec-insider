"""Plain-English names for SEC form types and 8-K item numbers (feature 026, FR-010, FR-011).

The stock research app lists a company's SEC filings by their form codes ("10-Q", "424B5",
"SC 13G/A") and an 8-K's item numbers ("2.02,9.01"), which a newcomer to markets cannot read.
This module gives each code a short name, one or two sentences on what the filing is and why an
investor might care, a kind for the filter (`KINDS`), and `dilution_signal`: True for filings
that usually announce or register a sale of new shares, or of securities that can become shares
(dilution: each existing share then owns a smaller part of the company).

Every form type with at least 100 filings in the data and every 8-K item number in it has its own
entry (checked by `tests/unit/test_web_glossary.py`); rarer members of a known family (another
424B prospectus, another fund form) get the family's description; any other code gets a general
description, never an error. An amendment ("10-K/A") reads as an amendment of its base form.
Pure functions, no I/O.
"""

import re
from typing import NamedTuple

KINDS: dict[str, str] = {
    "reports": "Annual & quarterly reports",
    "current": "Current reports (8-K)",
    "offerings": "Share & debt offerings",
    "insiders": "Insiders & big holders",
    "proxy": "Shareholder votes",
    "other": "Other",
}

UNKNOWN_FORM_DESCRIPTION = (
    "A type of SEC filing not described here; open the filing to see what it contains."
)
UNKNOWN_ITEM_NAME = "Item not described here"
UNKNOWN_ITEM_DESCRIPTION = (
    "An 8-K item number not described here; open the filing to see what it reports."
)


class _Entry(NamedTuple):
    kind: str
    name: str
    description: str
    dilution_signal: bool = False


# Forms that usually announce or register a sale of new shares (or of securities that can become
# shares). Mixed forms stay False and say so in their description: 424B2 and FWP (mostly banks'
# notes), 424B3 and 424B8 (any kind of prospectus), 424B7 (holders resell existing shares), and
# changes to registrations that already took effect (POS AM, S-8 POS...: often they remove unsold
# shares after a merger). Amendments ("S-1/A") carry their base form's flag.
_DILUTION_FORMS = frozenset(
    {
        "S-1", "S-1MEF", "S-2", "S-3", "S-3ASR", "S-3MEF", "S-3D", "S-4", "S-4MEF", "S-8",
        "S-11", "SB-1", "SB-2", "F-1", "F-1MEF", "F-3", "F-3ASR", "F-4", "F-10", "N-2",
        "N-2MEF", "N-2ASR", "424B1", "424B4", "424B5", "D", "REGDEX", "DRS", "1-A", "1-E",
        "253G1", "253G2", "C",
    }
)  # fmt: skip

_LATE = "; this gives it up to {days} more days. Late reports are sometimes a sign of accounting or money problems."  # noqa: E501
_PUHCA = "the old law for utility holding companies (repealed in 2006)"
_ADR = "ADRs (US-traded certificates that each stand for shares of a foreign company)"
_REG_A = "Regulation A, the SEC's simpler 'mini-IPO' rules for smaller public offerings"

_REPORTS: dict[str, tuple[str, str]] = {
    "10-K": (
        "Annual report",
        "The company's yearly report: audited financial statements, a description of the "
        "business and its risks, and management's discussion of the results.",
    ),
    "10-Q": (
        "Quarterly report",
        "The company's report for each of the first three quarters of its fiscal year, with "
        "unaudited financial statements and management's discussion of the results.",
    ),
    "10-KT": (
        "Annual report (transition)",
        "An annual report for the odd-length period created when the company changes the end "
        "date of its fiscal year.",
    ),
    "10-QT": (
        "Quarterly report (transition)",
        "A quarterly report for the odd-length period created when the company changes the end "
        "date of its fiscal year.",
    ),
    "10-K405": (
        "Annual report (10-K405)",
        "An annual report (10-K) under an old label, no longer used, showing that a box about "
        "insiders' ownership reports (Item 405) was ticked. Read it as a 10-K.",
    ),
    "10KSB": (
        "Small business annual report",
        "The yearly report of a small company on the simpler Form 10-KSB, used until 2009; read "
        "it like a 10-K.",
    ),
    "10KSB40": (
        "Small business annual report",
        "A small company's yearly report (10-KSB) under an old label showing that a box about "
        "insiders' ownership reports (Item 405) was ticked; read it like a 10-K.",
    ),
    "10QSB": (
        "Small business quarterly report",
        "The quarterly report of a small company on the simpler Form 10-QSB, used until 2008; "
        "read it like a 10-Q.",
    ),
    "20-F": (
        "Annual report (foreign company)",
        f"The yearly report of a foreign company whose shares or {_ADR} trade in the US; the "
        "foreign version of the 10-K.",
    ),
    "40-F": (
        "Annual report (Canadian company)",
        "The yearly report of a larger Canadian company, filed under the US-Canada joint system "
        "with its Canadian documents; it plays the role of the 10-K.",
    ),
    "11-K": (
        "Employee share plan report",
        "The yearly report of an employee savings or share purchase plan, such as a 401(k) "
        "plan, through which staff can buy the company's shares.",
    ),
    "ARS": (
        "Annual report to shareholders",
        "The annual report the company sends its shareholders with the proxy statement, often "
        "a glossy brochure; the 10-K has the full detail.",
    ),
    "10-D": (
        "Asset-backed payment report",
        "A periodic report on asset-backed securities (bonds paid from a pool of loans, such as "
        "car loans or mortgages): what was collected and paid out.",
    ),
    "ABS-EE": (
        "Asset-backed loan data",
        "Loan-by-loan data on the pool behind an asset-backed security (bonds paid from loans "
        "such as car loans or mortgages), attached to its reports.",
    ),
    "NT 10-K": (
        "Late annual report notice",
        "The company says its annual report will be late, and why" + _LATE.format(days=15),
    ),
    "NT 10-Q": (
        "Late quarterly report notice",
        "The company says its quarterly report will be late, and why" + _LATE.format(days=5),
    ),
    "NT 20-F": (
        "Late foreign annual report notice",
        "A foreign company says its annual report (20-F) will be late, and why; this gives it "
        "up to 15 more days.",
    ),
    "NT 11-K": (
        "Late employee plan report notice",
        "The company says the yearly report of its employee share plan (11-K) will be late, and "
        "why; this gives it up to 15 more days.",
    ),
    "NTN 10K": (
        "Late annual report notice",
        "Another label for a notice that the annual report (10-K or 10-KSB) will be late, and "
        "why; same purpose as NT 10-K.",
    ),
    "NTN 10Q": (
        "Late quarterly report notice",
        "Another label for a notice that the quarterly report (10-Q or 10-QSB) will be late, "
        "and why; same purpose as NT 10-Q.",
    ),
    "NT-NSAR": (
        "Late fund report notice",
        "An investment fund says its report on Form N-SAR will be late, and why.",
    ),
    "NT-NCSR": (
        "Late fund report notice",
        "An investment fund says its report to shareholders (Form N-CSR) will be late, and why.",
    ),
    "N-CSR": (
        "Fund annual report",
        "An investment fund's annual report to its shareholders, with financial statements and "
        "a list of its holdings.",
    ),
    "N-CSRS": (
        "Fund half-year report",
        "An investment fund's half-year report to its shareholders, with financial statements "
        "and a list of its holdings.",
    ),
    "N-Q": (
        "Fund quarterly holdings",
        "An investment fund's list of holdings after the first and third quarters of its fiscal "
        "year (an older form, replaced by Form N-PORT).",
    ),
    "NPORT-P": (
        "Fund monthly holdings report",
        "An investment fund's detailed monthly report of its holdings and risks to the SEC; the "
        "figures for the last month of each quarter are made public.",
    ),
    "NPORT-EX": (
        "Fund holdings list",
        "An investment fund's list of holdings at a quarter end, attached to its monthly "
        "portfolio report (Form N-PORT).",
    ),
    "N-30D": (
        "Fund report to shareholders",
        "An investment fund's annual or half-year report mailed to its shareholders (an old "
        "form, replaced by N-CSR).",
    ),
    "N-30B-2": (
        "Fund interim report",
        "A report an investment fund mailed to its shareholders other than its annual and "
        "half-year reports (an old form).",
    ),
    "NSAR-A": (
        "Fund half-year report (N-SAR)",
        "An investment fund's facts and figures on its operations for the first half of its "
        "fiscal year (an old form, replaced by N-CEN in 2018).",
    ),
    "NSAR-B": (
        "Fund annual report (N-SAR)",
        "An investment fund's facts and figures on its operations for its full fiscal year (an "
        "old form, replaced by N-CEN in 2018).",
    ),
    "NSAR-BT": (
        "Fund transition report (N-SAR)",
        "An investment fund's N-SAR report for the odd-length period created when it changes "
        "the end of its fiscal year.",
    ),
    "N-CEN": (
        "Fund annual census report",
        "An investment fund's yearly report of basic facts: how it is organized, its service "
        "providers, fees and some figures (since 2018).",
    ),
    "N-MFP": (
        "Money market fund holdings",
        "A money market fund's monthly report of its holdings and key figures (such a fund "
        "invests in very short-term, low-risk debt).",
    ),
    "1-K": (
        "Annual report (Regulation A)",
        f"The yearly report of a company that raised money under {_REG_A}.",
    ),
    "1-SA": (
        "Half-year report (Regulation A)",
        f"The half-year report of a company that raised money under {_REG_A}.",
    ),
    "C-AR": (
        "Crowdfunding annual report",
        "The yearly report of a company that raised money from the public through an online "
        "crowdfunding platform (Regulation Crowdfunding).",
    ),
}
_REPORTS["N-MFP2"] = _REPORTS["N-MFP3"] = _REPORTS["N-MFP"]

_CURRENT: dict[str, tuple[str, str]] = {
    "8-K": (
        "Current report",
        "A report of an important event, filed within four business days: results, deals, "
        "leadership changes and more. Its item numbers say what happened.",
    ),
    "6-K": (
        "Foreign company report",
        "A foreign company files news it publishes at home or sends its shareholders, such as "
        "results and press releases; the foreign counterpart of the 8-K.",
    ),
    "8-K12B": (
        "Current report (successor)",
        "An 8-K saying that a new company has taken over an old one's stock-exchange "
        "registration, such as after a reorganization under a new holding company.",
    ),
    "8-K12G3": (
        "Current report (successor)",
        "An 8-K saying that a new company has taken over an old one's SEC registration (Rule "
        "12g-3), such as after a merger or a reorganization.",
    ),
    "8-K15D5": (
        "Current report (successor)",
        "An 8-K saying that a new company has taken over an old one's duty to file reports with "
        "the SEC (Rule 15d-5).",
    ),
    "1-U": (
        "Current report (Regulation A)",
        "A company that raised money under Regulation A ('mini-IPO' rules) reports an important "
        "event, such as a change in control or of auditor.",
    ),
}

_INSIDERS: dict[str, tuple[str, str]] = {
    "3": (
        "Insider's first holdings report",
        "A new officer, director or 10%+ owner reports the company shares they own, within 10 "
        "days of taking the role (Form 3).",
    ),
    "4": (
        "Insider trade",
        "An officer, director or 10%+ owner reports buying or selling the company's shares, or "
        "receiving share awards, within two business days (Form 4).",
    ),
    "5": (
        "Insider annual report",
        "An insider's yearly report of holding changes that did not need a Form 4 at the time "
        "(such as some gifts) or were missed; due 45 days after the year ends.",
    ),
    "144": (
        "Planned insider share sale",
        "Notice that an insider or large holder plans to sell shares bought privately from the "
        "company or held as a controlling owner (Rule 144); existing shares, not new ones.",
    ),
    "SC 13D": (
        "Big holder report (active)",
        "An investor reports owning more than 5% of the shares, with plans that may include "
        "influencing or taking over the company, such as an activist fund.",
    ),
    "SC 13G": (
        "Big holder report (passive)",
        "An investor owning more than 5% of the shares files this shorter report when it does "
        "not seek control, such as a fund manager or an index fund.",
    ),
    "13F-HR": (
        "Fund manager holdings report",
        "A quarterly list of the US-listed shares held by an investment manager with over $100 "
        "million in them, such as a mutual fund or hedge fund firm.",
    ),
    "13F-NT": (
        "Fund manager holdings notice",
        "An investment manager's quarterly notice that its holdings are listed in another "
        "manager's 13F holdings report.",
    ),
    "13F-E": (
        "Fund manager holdings report",
        "An investment manager's quarterly report of its holdings, under an older label for "
        "Form 13F.",
    ),
    "13FCONP": (
        "Confidential holdings report",
        "An investment manager's 13F holdings report linked to a request to keep some of its "
        "positions confidential for a time.",
    ),
}

_PROXY: dict[str, tuple[str, str]] = {
    "DEF 14A": (
        "Proxy statement",
        "Sent to shareholders before a meeting: what they vote on (directors, executive pay, "
        "the auditor, proposals) and a request for their proxy, the right to vote for them.",
    ),
    "PRE 14A": (
        "Draft proxy statement",
        "A preliminary proxy statement, required when a vote covers non-routine matters such as "
        "a merger, a reverse split or a higher limit on shares the company may issue.",
    ),
    "DEFA14A": (
        "Extra proxy material",
        "Extra material about a shareholder vote filed by the company, such as letters, slides "
        "or press releases.",
    ),
    "DFAN14A": (
        "Proxy material from others",
        "Material about a shareholder vote filed by someone other than the company, usually an "
        "activist investor in a proxy fight (a contest for shareholders' votes).",
    ),
    "DEFM14A": (
        "Merger proxy statement",
        "The information sent to shareholders before they vote on a merger, or on a sale of the "
        "company or of its main assets.",
    ),
    "PREM14A": (
        "Draft merger proxy statement",
        "A preliminary merger proxy statement, for a vote on a merger or a sale of the company; "
        "the final one (DEFM14A) follows.",
    ),
    "DEFR14A": (
        "Revised proxy statement",
        "A revised version of a final proxy statement already sent to shareholders.",
    ),
    "PRER14A": (
        "Revised draft proxy statement",
        "A revised preliminary proxy statement, often after SEC staff comments; the final one "
        "follows.",
    ),
    "DEFC14A": (
        "Proxy statement (proxy fight)",
        "A final proxy statement in a contested vote (a proxy fight), where another group "
        "competes for shareholders' votes, such as for board seats.",
    ),
    "PREC14A": (
        "Draft proxy (proxy fight)",
        "A preliminary proxy statement in a contested vote (a proxy fight) over board seats or "
        "proposals.",
    ),
    "DEFN14A": (
        "Proxy statement by others",
        "A final proxy statement filed by a shareholder or group other than the company's "
        "management, usually an activist seeking votes.",
    ),
    "PREN14A": (
        "Draft proxy by others",
        "A preliminary proxy statement filed by a shareholder or group other than the company's "
        "management, usually an activist investor.",
    ),
    "DFRN14A": (
        "Revised proxy by others",
        "A revised final proxy statement filed by a shareholder or group other than the "
        "company's management.",
    ),
    "PRRN14A": (
        "Revised draft proxy by others",
        "A revised preliminary proxy statement filed by a shareholder or group other than the "
        "company's management.",
    ),
    "DEFS14A": (
        "Special meeting proxy",
        "The proxy statement for a special shareholder meeting, called outside the annual "
        "meeting to decide a specific matter.",
    ),
    "PRES14A": (
        "Draft special meeting proxy",
        "A preliminary proxy statement for a special shareholder meeting, called outside the "
        "annual meeting to decide a specific matter.",
    ),
    "DEF 14C": (
        "Information statement",
        "Tells shareholders about a decision already approved in writing by holders of a "
        "majority of the votes, so no vote is held (such as a reverse split).",
    ),
    "PRE 14C": (
        "Draft information statement",
        "A preliminary information statement: notice of a decision approved in writing by "
        "majority holders without a vote; the final one follows.",
    ),
    "PRER14C": (
        "Revised draft info statement",
        "A revised preliminary information statement (notice of a decision approved in writing "
        "by majority holders without a vote).",
    ),
    "DEFR14C": (
        "Revised information statement",
        "A revised final information statement (notice of a decision approved in writing by "
        "majority holders without a vote).",
    ),
    "DEFM14C": (
        "Merger information statement",
        "Tells shareholders about a merger or sale of the company already approved in writing "
        "by majority holders, so no vote is held.",
    ),
    "PREM14C": (
        "Draft merger info statement",
        "A preliminary information statement about a merger or sale approved in writing by "
        "majority holders without a vote.",
    ),
    "DEFA14C": (
        "Extra information material",
        "Extra material about an information statement (a decision approved in writing by "
        "majority holders without a vote).",
    ),
    "PX14A6G": (
        "Shareholder vote campaign",
        "A shareholder or group campaigns on a vote without asking for proxies, such as a "
        "letter urging votes against a proposal (an 'exempt solicitation').",
    ),
    "N-PX": (
        "Fund proxy voting record",
        "An investment fund's yearly record of how it voted at the shareholder meetings of the "
        "companies whose shares it owns.",
    ),
    "425": (
        "Merger communication",
        "A press release, slides or letter about a merger in which shares will be issued as "
        "payment, filed by the buyer or by the company being bought.",
    ),
    "SC TO-T": (
        "Takeover bid (tender offer)",
        "A buyer offers to purchase shareholders' shares directly, usually at a premium and "
        "often to take control (a tender offer). This is the buyer's statement.",
    ),
    "SC TO-I": (
        "Company buyback offer",
        "The company offers to buy back its own shares (or other securities) from holders at a "
        "set price for a limited time (an issuer tender offer).",
    ),
    "SC TO-C": (
        "Tender offer announcement",
        "Communications about a tender offer (an offer to buy shares directly from holders) "
        "made before the offer formally starts.",
    ),
    "SC 14D9": (
        "Board's tender offer advice",
        "The company's board tells shareholders whether it recommends accepting a tender offer "
        "(an offer to buy their shares directly), and why.",
    ),
    "SC14D9C": (
        "Tender offer response notice",
        "Communications by the company about a tender offer for its shares, made before its "
        "board's formal recommendation (Schedule 14D-9).",
    ),
    "SC 14D1": (
        "Takeover bid (old form)",
        "A buyer's offer to purchase shareholders' shares directly (a tender offer), on the "
        "form used until 2000.",
    ),
    "SC14D1F": (
        "Takeover bid (Canadian company)",
        "A tender offer (an offer to buy shares directly from holders) for a Canadian company, "
        "filed under the US-Canada joint disclosure system.",
    ),
    "SC 13E3": (
        "Going-private deal",
        "A deal that would take the company private, typically a buyout by insiders or a "
        "controlling holder; it explains the price and why it is said to be fair.",
    ),
    "SC 13E4": (
        "Company buyback offer (old)",
        "The company offers to buy back its own shares from holders (an issuer tender offer), "
        "on the form used until 2000.",
    ),
    "SC 14F1": (
        "Board majority change notice",
        "Notice that most of the board will change without a shareholder meeting, usually after "
        "a change in control, such as a private company merging into a listed shell.",
    ),
    "CB": (
        "Foreign takeover or rights notice",
        "Notice of a tender offer, merger or rights offering involving a foreign company with "
        "few US holders, which is exempt from most US filing rules.",
    ),
}

_OFFERINGS: dict[str, tuple[str, str]] = {
    "S-1": (
        "Offering registration",
        "Registers securities for sale to the public: an IPO (a company's first sale of shares), "
        "a later offering, or shares investors will resell. Usually means new shares.",
    ),
    "S-1MEF": (
        "Extra shares for an offering",
        "Adds up to 20% more securities to an offering already registered on Form S-1, "
        "typically on the day it is priced; usually more new shares.",
    ),
    "S-2": (
        "Offering registration (old)",
        "Registers securities for sale on a shorter form for established companies, used until "
        "2005; usually new shares.",
    ),
    "S-3": (
        "Shelf registration",
        "Registers shares, bonds or other securities an established company may sell later, "
        "in one or more sales ('off the shelf'). Often means new shares.",
    ),
    "S-3ASR": (
        "Automatic shelf registration",
        "A shelf registration by a large, well-known company that takes effect at once; it may "
        "cover new shares, bonds or other securities sold later.",
    ),
    "S-3MEF": (
        "Extra shares for a shelf sale",
        "Adds up to 20% more securities to an offering registered on Form S-3; usually more new "
        "shares.",
    ),
    "S-3D": (
        "Dividend reinvestment plan",
        "Registers shares for a plan that lets holders reinvest their dividends in new shares "
        "(a DRIP); it usually adds only a few shares.",
    ),
    "S-3DPOS": (
        "Dividend plan registration change",
        "A change to a dividend reinvestment plan's registration after it took effect, such as "
        "an update or the removal of unissued shares.",
    ),
    "S-4": (
        "Merger share registration",
        "Registers securities a company will issue to pay for a merger, or in an exchange offer "
        "(sometimes only bonds are swapped). New shares dilute existing holders.",
    ),
    "S-4MEF": (
        "Extra securities for a merger",
        "Adds up to 20% more securities to a merger or exchange offer registered on Form S-4.",
    ),
    "S-4 POS": (
        "Merger registration change",
        "A change to a merger or exchange offer registration (Form S-4) after it took effect, "
        "such as an update or the removal of unissued securities.",
    ),
    "S-8": (
        "Employee share plan registration",
        "Registers shares for employee stock plans (options, share awards, purchase plans). New "
        "shares dilute holders, usually by a small amount each year.",
    ),
    "S-8 POS": (
        "Employee plan registration change",
        "A change to an employee share plan's registration after it took effect, most often to "
        "remove unissued shares when a merger ends the plan.",
    ),
    "S-11": (
        "Real estate company registration",
        "Registers securities of a real estate company, such as a REIT (a company that owns "
        "property and pays out most of its income); usually new shares.",
    ),
    "SB-1": (
        "Small business registration (old)",
        "Registers securities of a small company for a public offering of up to $10 million, on "
        "a simple form used until 2008; usually new shares.",
    ),
    "SB-2": (
        "Small business registration",
        "Registers securities for sale by a small company, on a simpler form used until 2008; "
        "usually new shares, or shares investors will resell.",
    ),
    "SF-1": (
        "Asset-backed registration",
        "Registers asset-backed securities: bonds paid from a pool of loans or leases, such as "
        "car loans or credit card debts.",
    ),
    "SF-3": (
        "Asset-backed shelf registration",
        "A shelf registration for asset-backed securities (bonds paid from pools of loans), "
        "sold later in several issues.",
    ),
    "F-1": (
        "Foreign offering registration",
        "A foreign company registers securities for sale in the US, often in its US IPO; "
        "usually new shares or ADRs (US certificates standing for its shares).",
    ),
    "F-1MEF": (
        "Extra shares (foreign offering)",
        "Adds up to 20% more securities to a foreign company's offering registered on Form F-1; "
        "usually more new shares.",
    ),
    "F-3": (
        "Foreign shelf registration",
        "A foreign company registers shares, bonds or other securities it may sell later; the "
        "foreign version of Form S-3. Often means new shares.",
    ),
    "F-3ASR": (
        "Foreign automatic shelf",
        "A shelf registration by a large, well-known foreign company that takes effect at once; "
        "it may cover new shares, bonds or other securities.",
    ),
    "F-4": (
        "Foreign merger share registration",
        "A foreign company registers securities it will issue to pay for a merger or in an "
        "exchange offer; the foreign version of Form S-4.",
    ),
    "F-6": (
        "ADR registration",
        f"Registers {_ADR}. It is not by itself a sale of new shares.",
    ),
    "F-6EF": (
        "ADR registration (immediate)",
        f"Registers {_ADR}, taking effect as soon as it is filed.",
    ),
    "F-6 POS": (
        "ADR registration change",
        "A change to an ADR registration after it took effect, such as a new number of shares "
        "per ADR (a US certificate standing for foreign shares).",
    ),
    "F-10": (
        "Canadian offering registration",
        "A Canadian company registers securities for sale in the US with its Canadian "
        "prospectus (US-Canada joint system); often new shares.",
    ),
    "F-10POS": (
        "Canadian registration change",
        "A change to a Canadian company's registration on Form F-10 after it took effect.",
    ),
    "424B1": (
        "Final prospectus (priced)",
        "The final prospectus (offering document) with the price and other facts left out of "
        "the registration; most often an IPO or other sale of new shares.",
    ),
    "424B2": (
        "Shelf prospectus (mostly notes)",
        "Price and terms of a sale from a shelf registration. Mostly bonds and structured notes "
        "(returns tied to an index or stock) sold by large banks; rarely new shares.",
    ),
    "424B3": (
        "Prospectus update",
        "A prospectus (offering document) or supplement with new facts, such as for shares "
        "investors resell, a merger or an ongoing offering. Sometimes new shares, often not.",
    ),
    "424B4": (
        "Final prospectus",
        "The final prospectus (offering document) of an offering, with its price; most often an "
        "IPO or other sale of new shares to the public.",
    ),
    "424B5": (
        "Shelf sale prospectus",
        "Prospectus for a sale from a shelf registration (Form S-3 or F-3): often new shares "
        "sold to the public or to investors; for large companies often bonds.",
    ),
    "424B7": (
        "Resale prospectus (holders)",
        "Names existing holders selling their shares under a shelf registration (a secondary "
        "sale); the company issues no new shares and gets no money.",
    ),
    "424B8": (
        "Late-filed prospectus",
        "A prospectus filed after the SEC's deadline; it can be of any kind (new shares, a "
        "resale or notes), so read it to see what is offered.",
    ),
    "424A": (
        "Preliminary prospectus",
        "A draft prospectus used to market an offering before its registration takes effect; "
        "the price and amount may still change.",
    ),
    "424H": (
        "Draft asset-backed prospectus",
        "A preliminary prospectus for asset-backed securities (bonds paid from pools of loans "
        "such as car loans), filed days before they are sold.",
    ),
    "424I": (
        "Yearly sales and fee report",
        "An exchange-traded product that is not a registered fund (such as a gold or oil trust) "
        "reports the shares it sold in its fiscal year, to pay SEC fees.",
    ),
    "FWP": (
        "Offering marketing material",
        "A 'free writing prospectus': a term sheet, slides or other marketing material for a "
        "registered offering. Mostly used by banks for notes; rarely new shares.",
    ),
    "D": (
        "Private sale notice (Form D)",
        "The company sold securities privately to chosen investors without SEC registration "
        "(Regulation D); usually new shares or securities that can become shares.",
    ),
    "REGDEX": (
        "Private sale notice (old Form D)",
        "An older, paper-filed Form D: the company sold securities privately without SEC "
        "registration (Regulation D); usually new shares.",
    ),
    "DRS": (
        "Confidential draft registration",
        "A draft registration statement, usually for an IPO or a share sale, that the SEC "
        "reviews privately; it is made public before the sale.",
    ),
    "DRSLTR": (
        "Letter on a draft registration",
        "The company's letter to SEC staff about its confidential draft registration "
        "statement, usually answering their comments.",
    ),
    "EFFECT": (
        "Registration effective",
        "The SEC's notice that a registration statement has taken effect, so the securities it "
        "covers may now be sold.",
    ),
    "QUALIF": (
        "Regulation A offering approved",
        "The SEC's notice that an offering under Regulation A ('mini-IPO' rules) is qualified, "
        "so its securities may now be sold.",
    ),
    "RW": (
        "Registration withdrawal",
        "The company asks to withdraw a registration statement, usually because a planned "
        "offering or deal was dropped; nothing was sold under it.",
    ),
    "RW WD": (
        "Withdrawal request cancelled",
        "The company cancels its earlier request to withdraw a registration statement.",
    ),
    "AW": (
        "Amendment withdrawal",
        "The company withdraws an amendment it filed to a registration statement.",
    ),
    "DEL AM": (
        "Delaying amendment",
        "An amendment that stops a registration statement from taking effect automatically, "
        "giving the company and the SEC more time.",
    ),
    "POS AM": (
        "Registration change",
        "A change to a registration statement after it took effect, such as an updated "
        "prospectus or the removal of unsold securities (common after a merger).",
    ),
    "POSASR": (
        "Automatic shelf change",
        "A change to a large company's automatic shelf registration, such as adding new types "
        "of securities or removing unsold ones.",
    ),
    "POS EX": (
        "Exhibits added to registration",
        "A change to a registration statement that only adds exhibits (attached documents), "
        "such as a legal opinion or an agreement.",
    ),
    "POS AMI": (
        "Fund registration change",
        "A change to an investment fund's registration made only under the Investment Company "
        "Act, the law that governs funds.",
    ),
    "POS 8C": (
        "Closed-end fund update",
        "A change to the registration of a closed-end fund (one with a fixed number of shares "
        "traded on an exchange) or a business development company.",
    ),
    "POS462B": (
        "Extra-shares registration change",
        "A change to a short registration that added up to 20% more securities to an offering "
        "(SEC Rule 462(b)).",
    ),
    "1-A": (
        "Regulation A offering",
        "A company files to sell securities under Regulation A, the SEC's simpler 'mini-IPO' "
        "rules for raising up to $75 million a year; usually new shares.",
    ),
    "1-A POS": (
        "Regulation A offering change",
        "A change to a Regulation A ('mini-IPO') offering after it was approved, such as a "
        "yearly update or new terms.",
    ),
    "1-A-W": (
        "Regulation A offering withdrawn",
        "The company withdraws its offering statement under Regulation A ('mini-IPO' rules).",
    ),
    "253G1": (
        "Regulation A offering circular",
        "The offering document (circular) of a Regulation A ('mini-IPO') sale with its final "
        "details; such sales are usually new shares.",
    ),
    "253G2": (
        "Regulation A circular update",
        "An offering circular or supplement with new or changed facts for a Regulation A "
        "('mini-IPO') sale; such sales are usually new shares.",
    ),
    "1-Z": (
        "Regulation A exit report",
        "A company reports the results of its finished Regulation A offering, or that it stops "
        "filing Regulation A reports.",
    ),
    "1-E": (
        "Small investment firm offering",
        "Notice of a small offering (Regulation E) by a small business investment company or a "
        "business development company; usually new shares.",
    ),
    "C": (
        "Crowdfunding offering",
        "A company offers securities to the public through an online crowdfunding platform "
        "(Regulation Crowdfunding); usually new shares or similar.",
    ),
    "N-2": (
        "Closed-end fund registration",
        "Registers shares or notes a closed-end fund or a business development company (a firm "
        "investing in smaller companies) will sell; often new shares.",
    ),
    "N-2MEF": (
        "Extra shares (closed-end fund)",
        "Adds up to 20% more securities to a closed-end fund's or business development "
        "company's offering registered on Form N-2.",
    ),
    "N-2ASR": (
        "Closed-end fund automatic shelf",
        "A shelf registration by a large closed-end fund or business development company that "
        "takes effect at once; it may cover new shares or notes.",
    ),
    "N-14": (
        "Fund merger registration",
        "Registers fund shares to be issued when one investment fund merges into another.",
    ),
    "N-14 8C": (
        "Closed-end fund merger",
        "Registers shares a closed-end fund will issue when another fund merges into it.",
    ),
    "485BPOS": (
        "Fund prospectus update",
        "A mutual fund or ETF (exchange-traded fund) updates its registration and prospectus, "
        "typically once a year; it takes effect at once.",
    ),
    "485APOS": (
        "Fund registration change",
        "A mutual fund or ETF files a change to its registration, such as a new fund, that "
        "takes effect after 60 or 75 days so the SEC can review it.",
    ),
    "485BXT": (
        "Fund registration date delay",
        "A fund postpones the date when an earlier change to its registration takes effect.",
    ),
    "486BPOS": (
        "Interval fund prospectus update",
        "An interval fund (a closed-end fund that buys back shares at set times) updates its "
        "registration; it takes effect at once.",
    ),
    "486APOS": (
        "Interval fund registration change",
        "An interval fund (a closed-end fund that buys back shares at set times) files a change "
        "to its registration that takes effect after an SEC review period.",
    ),
    "486BXT": (
        "Interval fund date delay",
        "An interval fund postpones the date when an earlier change to its registration takes "
        "effect.",
    ),
    "497": (
        "Fund prospectus material",
        "A fund's final prospectus or a supplement with changes, filed when first used; mostly "
        "mutual funds and ETFs.",
    ),
    "497K": (
        "Fund summary prospectus",
        "The short summary prospectus of a mutual fund or ETF: its goal, fees, risks and past "
        "returns.",
    ),
    "497J": (
        "Fund prospectus unchanged",
        "A fund certifies that its final prospectus is the same as in its latest registration "
        "filing.",
    ),
    "497AD": (
        "Fund advertisement",
        "An advertisement for an investment fund, filed with the SEC.",
    ),
    "497K3B": (
        "Fund profile",
        "A short profile of a mutual fund describing its goals, risks and fees (an older, "
        "optional summary document).",
    ),
    "497VPU": (
        "Variable annuity summary update",
        "An updating summary prospectus for a variable annuity or variable life insurance "
        "contract (insurance whose value follows investment funds).",
    ),
    "24F-2NT": (
        "Fund shares sold notice",
        "A fund's yearly notice of how many of its shares it sold, used to pay the SEC's "
        "registration fee.",
    ),
    "T-3": (
        "Bond terms approval request",
        "A request to approve the terms (indenture) of bonds issued without registration, often "
        "in a debt exchange or a bankruptcy reorganization.",
    ),
    "305B2": (
        "Bond trustee eligibility",
        "A statement that a bank or trust company may act as trustee for bonds, protecting "
        "bondholders' interests, under an existing registration.",
    ),
    "SUPPL": (
        "Foreign offering supplement",
        "Voluntary extra material filed by a foreign company, often Canadian, for a securities "
        "offering in the US, such as a prospectus supplement.",
    ),
}

_OTHER: dict[str, tuple[str, str]] = {
    "CORRESP": (
        "Letter to the SEC",
        "The company's letter to SEC staff, usually answering their questions on its filings; "
        "such letters are made public later.",
    ),
    "UPLOAD": (
        "Letter from the SEC",
        "A letter from SEC staff to the company, usually with questions or comments on its "
        "filings (a 'comment letter'); made public later.",
    ),
    "CT ORDER": (
        "Confidential treatment order",
        "The SEC agrees to keep parts of a filed document (often contract terms such as prices) "
        "confidential for a set time.",
    ),
    "NO ACT": (
        "SEC no-action letter",
        "SEC staff say they would not recommend enforcement over a planned step, often letting "
        "a company leave a shareholder proposal off its ballot.",
    ),
    "SEC STAFF LETTER": (
        "Letter from SEC staff",
        "A letter from SEC staff about the filer's filings or requests.",
    ),
    "SEC STAFF ACTION": (
        "SEC staff action",
        "A record of an action taken by SEC staff on the filer's filing or request.",
    ),
    "REVOKED": (
        "Registration revoked",
        "The SEC revoked the registration of the company's securities, usually for not filing "
        "reports, so they can no longer be traded publicly in the US.",
    ),
    "8-A12B": (
        "Exchange listing registration",
        "Registers a class of the company's securities so they can be listed on a stock "
        "exchange; usually filed around an IPO or a new listing.",
    ),
    "8-A12G": (
        "Securities registration (12(g))",
        "Registers a class of the company's securities with the SEC (section 12(g)), so it "
        "must file regular reports; often for shares not listed on an exchange.",
    ),
    "10-12B": (
        "Form 10 listing registration",
        "Registers a class of securities for listing on a stock exchange using Form 10, often "
        "for a spin-off (a business separated from its parent company).",
    ),
    "10-12G": (
        "Form 10 registration",
        "Registers a class of securities with the SEC using Form 10, without an offering, so "
        "the company starts filing reports.",
    ),
    "10SB12G": (
        "Small business registration",
        "Registers a small company's securities with the SEC on Form 10-SB (used until 2008), "
        "so it starts filing reports.",
    ),
    "20FR12B": (
        "Foreign listing registration",
        "A foreign company registers a class of securities to list them on a US stock exchange, "
        "using Form 20-F.",
    ),
    "20FR12G": (
        "Foreign securities registration",
        "A foreign company registers a class of securities with the SEC using Form 20-F "
        "(section 12(g)), so it starts filing reports.",
    ),
    "40FR12B": (
        "Canadian listing registration",
        "A Canadian company registers a class of securities to list them on a US stock "
        "exchange, using Form 40-F.",
    ),
    "15-12B": (
        "Exchange registration ended",
        "The company ends the registration of a class of securities listed on an exchange, "
        "often after a merger or a delisting.",
    ),
    "15-12G": (
        "Registration ended",
        "The company ends the registration of a class of its securities and usually stops "
        "filing reports ('going dark'), such as after a merger or with few holders.",
    ),
    "15-15D": (
        "Reporting suspended",
        "The company suspends its duty to file reports with the SEC (section 15(d)), such as "
        "after a merger or because it has few holders.",
    ),
    "15F-12B": (
        "Foreign registration ended",
        "A foreign company ends its US registration and stops filing reports with the SEC, "
        "usually after leaving a US stock exchange.",
    ),
    "15F-12G": (
        "Foreign registration ended",
        "A foreign company ends its US registration (section 12(g)) and stops filing reports "
        "with the SEC.",
    ),
    "15F-15D": (
        "Foreign reporting ended",
        "A foreign company ends its duty to file reports with the SEC (section 15(d)).",
    ),
    "25": (
        "Delisting notice (company)",
        "The company tells the SEC it is removing a class of securities from a stock exchange "
        "(delisting), such as after a merger or to move to another market.",
    ),
    "25-NSE": (
        "Delisting notice (exchange)",
        "A stock exchange tells the SEC it is removing a security from listing, such as after a "
        "merger, a redemption or a failure to meet listing rules.",
    ),
    "CERT": (
        "Exchange listing approval",
        "A stock exchange certifies to the SEC that it has approved the company's securities "
        "for listing.",
    ),
    "CERTNYS": (
        "Listing approval (NYSE)",
        "The New York Stock Exchange certifies to the SEC that it has approved the company's "
        "securities for listing.",
    ),
    "CERTNAS": (
        "Listing approval (Nasdaq)",
        "Nasdaq certifies to the SEC that it has approved the company's securities for listing.",
    ),
    "CERTAMX": (
        "Listing approval (AMEX)",
        "The American Stock Exchange (now NYSE American) certifies to the SEC that it has "
        "approved the company's securities for listing.",
    ),
    "CERTPAC": (
        "Listing approval (Pacific)",
        "The Pacific Exchange (later part of NYSE Arca) certifies to the SEC that it has "
        "approved the company's securities for listing.",
    ),
    "CERTARCA": (
        "Listing approval (NYSE Arca)",
        "NYSE Arca certifies to the SEC that it has approved the company's securities for listing.",
    ),
    "SD": (
        "Specialized disclosure report",
        "A yearly report on whether products contain 'conflict minerals' (tin, tungsten, "
        "tantalum, gold) from Congo or nearby countries; some report payments to governments.",
    ),
    "IRANNOTICE": (
        "Iran-related activity notice",
        "Notice that the company's latest annual or quarterly report discloses dealings related "
        "to Iran or other sanctioned parties, as US law requires.",
    ),
    "10-C": (
        "Nasdaq share count change",
        "An old notice by a Nasdaq-quoted company that its number of shares outstanding changed "
        "by more than 5%, or that its name changed.",
    ),
    "SE": (
        "Paper exhibits form",
        "Cover form for exhibits (attached documents) delivered on paper rather than "
        "electronically.",
    ),
    "F-X": (
        "US legal agent appointment",
        "A foreign company names a US agent that can receive legal papers on its behalf, "
        "required with certain filings.",
    ),
    "F-N": (
        "US legal agent (foreign bank)",
        "A foreign bank or insurance company names a US agent that can receive legal papers on "
        "its behalf.",
    ),
    "ABS-15G": (
        "Asset-backed repurchase report",
        "A firm that packages loans into bonds (asset-backed securities) reports demands to buy "
        "back faulty loans, or outside reviews of the loans.",
    ),
    "SBSE-A": (
        "Swap dealer registration",
        "A dealer in security-based swaps (contracts whose value follows a stock, bond or "
        "loan), usually a large bank, registers with the SEC.",
    ),
    "40-17G": (
        "Fund fidelity bond",
        "A fund files its fidelity bond: insurance against theft or fraud by its staff, "
        "required by fund law.",
    ),
    "40-17F2": (
        "Fund custody check",
        "An accountant's certificate after checking that the securities a fund holds in its own "
        "custody are really there.",
    ),
    "40-APP": (
        "Fund exemption request",
        "An investment fund or adviser asks the SEC for an exemption from parts of fund law (the "
        "Investment Company Act), such as to launch an ETF.",
    ),
    "40-6C": (
        "Fund exemption request (6(c))",
        "A request for an SEC order exempting a fund or company from parts of fund law (the "
        "Investment Company Act, section 6(c)).",
    ),
    "40-33": (
        "Fund lawsuit copy",
        "Copy of a lawsuit brought for shareholders against an investment fund or its managers, "
        "filed with the SEC as fund law requires.",
    ),
    "APP NTC": (
        "Exemption request notice",
        "The SEC's public notice of a request for an exemption from fund law, usually filed on "
        "Form 40-APP.",
    ),
    "APP ORDR": (
        "Exemption order",
        "The SEC's order granting a requested exemption from fund law.",
    ),
    "APP WD": (
        "Exemption request withdrawn",
        "The applicant withdraws its request for an exemption from fund law.",
    ),
    "N-8A": (
        "Fund registration notice",
        "Notice that an investment fund registers under the Investment Company Act, the law "
        "that governs funds.",
    ),
    "N-8F": (
        "Fund deregistration request",
        "An investment fund asks to end its registration, usually because it has closed, merged "
        "or been liquidated.",
    ),
    "N-8F NTC": (
        "Fund deregistration notice",
        "The SEC's public notice that an investment fund has asked to end its registration.",
    ),
    "N-8F ORDR": (
        "Fund deregistration order",
        "The SEC's order ending an investment fund's registration.",
    ),
    "N-23C-1": (
        "Fund buyback report",
        "A closed-end fund reports purchases of its own shares (a buyback).",
    ),
    "N-23C-2": (
        "Fund redemption notice",
        "A closed-end fund gives notice that it intends to call or redeem (buy back on set "
        "terms) some of its securities, such as preferred shares.",
    ),
    "N-23C3A": (
        "Interval fund buyback notice",
        "An interval fund's notice of its regular offer to buy back part of its shares from "
        "holders.",
    ),
    "N-23C3B": (
        "Fund one-off buyback notice",
        "A closed-end interval fund's notice of an extra, one-off offer to buy back part of its "
        "shares from holders.",
    ),
    "N-54A": (
        "BDC election notice",
        "A company elects to be a business development company (BDC): a fund-like firm that "
        "invests in or lends to smaller companies.",
    ),
    "N-54C": (
        "BDC election withdrawn",
        "A company withdraws its election to be a business development company (BDC).",
    ),
    "N-6F": (
        "Intent to become a BDC",
        "A company gives notice that it intends to elect to be a business development company "
        "(BDC), a firm that invests in smaller companies.",
    ),
    "U-1": (
        "Utility holding company request",
        f"An application under {_PUHCA}, such as to issue securities or buy a business.",
    ),
    "POS AMC": (
        "Utility request change",
        f"A change to an application (Form U-1) under {_PUHCA}.",
    ),
    "U-12-IB": (
        "Utility lobbying statement",
        f"A yearly statement under {_PUHCA} by a person paid to represent the company before "
        "Congress or regulators.",
    ),
    "U-6B-2": (
        "Utility securities issue notice",
        f"A notice under {_PUHCA} that a company issued, renewed or guaranteed securities.",
    ),
    "U-3A-2": (
        "Utility law exemption claim",
        f"A holding company's yearly claim of exemption from {_PUHCA}.",
    ),
    "U-9C-3": (
        "Utility energy business report",
        f"A quarterly report under {_PUHCA} on investments in energy-related businesses.",
    ),
    "U-57": (
        "Foreign utility status notice",
        f"A notice under {_PUHCA} that a business qualifies as a foreign utility company.",
    ),
    "U5S": (
        "Utility holding company report",
        f"The annual report of a registered utility holding company under {_PUHCA}.",
    ),
    "35-CERT": (
        "Utility deal certificate",
        f"A certificate under {_PUHCA} that an approved transaction was carried out on its terms.",
    ),
}

_FORMS: dict[str, _Entry] = {
    code: _Entry(kind, name, description, code in _DILUTION_FORMS)
    for kind, table in (
        ("reports", _REPORTS),
        ("current", _CURRENT),
        ("offerings", _OFFERINGS),
        ("insiders", _INSIDERS),
        ("proxy", _PROXY),
        ("other", _OTHER),
    )
    for code, (name, description) in table.items()
}

# Other spellings of the same form.
_ALIASES: dict[str, str] = {
    "SCHEDULE 13D": "SC 13D",
    "SCHEDULE 13G": "SC 13G",
    "10-KSB": "10KSB",
    "10-KSB40": "10KSB40",
    "10-QSB": "10QSB",
}

# Families, tried in order after the exact entries: a rarer code of a known family gets the
# family's general description.
_FAMILIES: tuple[tuple[re.Pattern[str], _Entry], ...] = tuple(
    (re.compile(pattern), entry)
    for pattern, entry in (
        (
            r"8-K\S*",
            _Entry(
                "current",
                "Current report (variant)",
                "A variant of the 8-K current report, which reports an important event such as "
                "results, deals or leadership changes.",
            ),
        ),
        (
            r"10-?K\S*",
            _Entry(
                "reports",
                "Annual report (variant)",
                "A variant of the annual report (10-K): the company's yearly report with "
                "audited financial statements.",
            ),
        ),
        (
            r"10-?Q\S*",
            _Entry(
                "reports",
                "Quarterly report (variant)",
                "A variant of the quarterly report (10-Q), with unaudited financial statements "
                "for the quarter.",
            ),
        ),
        (
            r"NTN?[ -].+",
            _Entry(
                "reports",
                "Late filing notice",
                "The filer tells the SEC that a required report will be late, and why.",
            ),
        ),
        (
            r"[SFN]-\d+\S*MEF",
            _Entry(
                "offerings",
                "Extra securities for an offering",
                "Adds up to 20% more securities to an offering already registered; usually "
                "more new shares.",
                True,
            ),
        ),
        (
            r"424\w+",
            _Entry(
                "offerings",
                "Prospectus",
                "A prospectus (offering document) giving the terms of a registered offering; it "
                "may cover new shares, shares resold by holders, or bonds.",
            ),
        ),
        (
            r"48[56]\S*",
            _Entry(
                "offerings",
                "Fund registration update",
                "An update to an investment fund's registration and prospectus.",
            ),
        ),
        (
            r"497\S*",
            _Entry(
                "offerings",
                "Fund prospectus material",
                "A fund's prospectus, summary or supplement, filed when first used.",
            ),
        ),
        (
            r".*POS.*",
            _Entry(
                "offerings",
                "Registration change",
                "A change to a registration statement (the filing that allows a public sale of "
                "securities) after it took effect.",
            ),
        ),
        (
            r"(DEF|PRE|DFAN|DFRN|PRRN)[A-Z]? ?14A",
            _Entry(
                "proxy",
                "Proxy material",
                "A document about a shareholder vote, such as a proxy statement or related "
                "material sent to shareholders before a meeting.",
            ),
        ),
        (
            r"(DEF|PRE)[A-Z]? ?14C",
            _Entry(
                "proxy",
                "Information statement material",
                "A document telling shareholders about a decision approved in writing by "
                "majority holders, without a vote.",
            ),
        ),
        (
            r"PX14A\S*",
            _Entry(
                "proxy",
                "Shareholder vote campaign",
                "A shareholder or group campaigns on a vote without asking for proxies (an "
                "'exempt solicitation').",
            ),
        ),
        (
            r"SC ?(TO|14D)\S*",
            _Entry(
                "proxy",
                "Tender offer filing",
                "A filing about a tender offer: an offer, by the company or an outside buyer, "
                "to buy shares directly from shareholders.",
            ),
        ),
        (
            r"SC ?13E\S*",
            _Entry(
                "proxy",
                "Buyback or going-private filing",
                "A filing about a company buying back its own shares, or being taken private by "
                "insiders or a controlling holder.",
            ),
        ),
        (
            r"(SC|SCHEDULE) ?13[DG]\S*",
            _Entry(
                "insiders",
                "Big holder report",
                "An investor reports owning more than 5% of the company's shares.",
            ),
        ),
        (
            r"13F\S*",
            _Entry(
                "insiders",
                "Fund manager holdings filing",
                "A filing about an investment manager's quarterly report of its holdings "
                "(Form 13F).",
            ),
        ),
        (
            r"S-\d+\S*",
            _Entry(
                "offerings",
                "Registration statement",
                "Registers securities to be sold or issued to the public; read it to see "
                "whether they are new shares.",
            ),
        ),
        (
            r"F-\d+\S*",
            _Entry(
                "offerings",
                "Foreign company registration",
                "A foreign company registers securities to be sold or issued in the US; read it "
                "to see whether they are new shares.",
            ),
        ),
        (
            r"SB-\d+\S*",
            _Entry(
                "offerings",
                "Small business registration",
                "Registers securities of a small company on an older, simpler form; read it to "
                "see whether they are new shares.",
            ),
        ),
        (
            r"SF-\d+\S*",
            _Entry(
                "offerings",
                "Asset-backed registration",
                "Registers asset-backed securities: bonds paid from a pool of loans such as car "
                "loans or mortgages.",
            ),
        ),
        (
            r"253G\d",
            _Entry(
                "offerings",
                "Regulation A offering circular",
                f"An offering document for a sale under {_REG_A}; usually new shares.",
                True,
            ),
        ),
        (
            r"1-[A-Z].*",
            _Entry(
                "offerings",
                "Regulation A filing",
                f"A filing about an offering under {_REG_A}.",
            ),
        ),
        (
            r"C-\S+",
            _Entry(
                "offerings",
                "Crowdfunding filing",
                "A filing about an offering through an online crowdfunding platform (Regulation "
                "Crowdfunding).",
            ),
        ),
        (
            r"NPORT\S*|NSAR\S*|N-CSR\S*|N-MFP\S*",
            _Entry(
                "reports",
                "Fund report",
                "A periodic report by an investment fund on its holdings and operations.",
            ),
        ),
        (
            r"N-.+|40-.+|APP .+",
            _Entry(
                "other",
                "Investment fund filing",
                "A filing by or about an investment fund (such as a mutual fund, ETF or "
                "closed-end fund) under the law that governs funds.",
            ),
        ),
        (
            r"(10-|10SB|20FR|40FR)12[BG]\S*|8-A\S*",
            _Entry(
                "other",
                "Securities registration",
                "Registers a class of the company's securities with the SEC, so it files "
                "regular reports; often around a listing.",
            ),
        ),
        (
            r"15F?-\S+",
            _Entry(
                "other",
                "Registration ended",
                "The company ends a registration with the SEC and usually stops filing reports.",
            ),
        ),
        (
            r"CERT\S*",
            _Entry(
                "other",
                "Exchange listing approval",
                "A stock exchange certifies to the SEC that it has approved securities for "
                "listing.",
            ),
        ),
        (
            r"ABS-\S+",
            _Entry(
                "reports",
                "Asset-backed securities filing",
                "A filing about asset-backed securities: bonds paid from a pool of loans such "
                "as car loans or mortgages.",
            ),
        ),
        (
            r"U-\S+|U\d\S*|35-\S+",
            _Entry(
                "other",
                "Utility holding company filing",
                f"A filing under {_PUHCA}.",
            ),
        ),
        (
            r"SBSE\S*",
            _Entry(
                "other",
                "Swap dealer filing",
                "A filing by a dealer in security-based swaps (contracts whose value follows a "
                "stock, bond or loan).",
            ),
        ),
    )
)

_OLD = "Old numbering (before August 2004): "
_OLD_2003 = "Old numbering (2003 to August 2004): "

_ITEMS: dict[str, tuple[str, str]] = {
    "1.01": (
        "Major agreement signed",
        "The company signed an important contract outside its everyday business, such as a "
        "loan agreement, a merger agreement or a large supply deal.",
    ),
    "1.02": (
        "Major agreement ended",
        "An important contract of the company was terminated before the end of its term.",
    ),
    "1.03": (
        "Bankruptcy or receivership",
        "The company or a major subsidiary entered bankruptcy or receivership. Shareholders are "
        "paid last, after lenders, and often receive little or nothing.",
    ),
    "1.04": (
        "Mine safety issue",
        "A US mine run by the company received a shutdown order or a notice of a pattern of "
        "serious safety violations from the mine safety regulator.",
    ),
    "1.05": (
        "Cybersecurity incident",
        "The company found a cybersecurity incident (such as a hack) that it judges material, "
        "and describes its nature, scope and likely impact (since December 2023).",
    ),
    "2.01": (
        "Acquisition or sale completed",
        "The company completed buying or selling a significant business or assets.",
    ),
    "2.02": (
        "Results announced",
        "The company released its quarterly or annual results, usually in an attached press "
        "release.",
    ),
    "2.03": (
        "New debt or obligation",
        "The company took on a significant new debt or similar obligation, such as a loan, "
        "bonds, a credit line or a guarantee.",
    ),
    "2.04": (
        "Debt made due early",
        "An event, such as a default, made a debt or other obligation due sooner or larger. "
        "This can be a sign of financial stress.",
    ),
    "2.05": (
        "Restructuring costs",
        "The company committed to a plan to exit or cut activities, such as layoffs or closing "
        "sites, with significant costs.",
    ),
    "2.06": (
        "Asset write-down",
        "The company concluded that some assets, such as goodwill from an acquisition, are "
        "worth much less than recorded (an impairment).",
    ),
    "3.01": (
        "Listing problem or transfer",
        "The stock exchange says the company fails a listing rule (such as a share price under "
        "$1) or will delist it, or the company moves its listing.",
    ),
    "3.02": (
        "Shares sold privately",
        "The company sold shares (or securities convertible into shares) without a public "
        "offering; existing holders are diluted.",
    ),
    "3.03": (
        "Shareholder rights changed",
        "The rights of shareholders changed, such as through a reverse split, new terms for a "
        "class of shares, or a plan to block takeovers (a 'poison pill').",
    ),
    "4.01": (
        "Auditor changed",
        "The company's outside auditor resigned, was dismissed or was replaced; the filing says "
        "whether they disagreed.",
    ),
    "4.02": (
        "Past financials unreliable",
        "Earlier financial statements should no longer be relied on because of an error, and "
        "will be corrected (a restatement).",
    ),
    "5.01": (
        "Change in control",
        "Someone gained control of the company, such as through a takeover or a large share "
        "purchase.",
    ),
    "5.02": (
        "Directors or officers change",
        "A director or top officer left or joined, or the pay arrangements of top officers "
        "changed.",
    ),
    "5.03": (
        "Charter or bylaws amended",
        "The company changed its articles of incorporation or bylaws (its basic rules), such as "
        "for a reverse split, or changed its fiscal year.",
    ),
    "5.04": (
        "Employee plan trading halt",
        "Employees temporarily cannot trade company shares in their retirement plan (a blackout), "
        "so directors and officers may not trade them either.",
    ),
    "5.05": (
        "Code of ethics changed",
        "The company changed its code of ethics or waived it for a top officer.",
    ),
    "5.06": (
        "Shell status changed",
        "The company stopped being a shell company (one with no real business), usually after "
        "merging with an operating business.",
    ),
    "5.07": (
        "Shareholder vote results",
        "Results of the votes at a shareholder meeting: directors elected, pay votes and other "
        "proposals.",
    ),
    "5.08": (
        "Director nomination deadline",
        "Sets the deadline for shareholders to nominate directors, when the meeting date moved "
        "substantially from the previous year's.",
    ),
    "6.01": (
        "Asset-backed: information material",
        "Information and calculations for investors in asset-backed securities (bonds paid from "
        "a pool of loans).",
    ),
    "6.02": (
        "Asset-backed: servicer or trustee change",
        "The firm that collects the loans, or the trustee, of an asset-backed security (bonds "
        "paid from a pool of loans) changed.",
    ),
    "6.03": (
        "Asset-backed: credit support change",
        "A change in the protection (such as insurance or a guarantee) for investors in an "
        "asset-backed security (bonds paid from a pool of loans).",
    ),
    "6.04": (
        "Asset-backed: payment missed",
        "A required payment to holders of an asset-backed security (bonds paid from a pool of "
        "loans) was not made when due.",
    ),
    "6.05": (
        "Asset-backed: pool update",
        "Updated facts on the pool of loans behind an asset-backed security, which changed "
        "materially after the offering.",
    ),
    "6.06": (
        "Asset-backed: past pool data",
        "How earlier, similar pools of loans performed (static pool data), for an asset-backed "
        "security.",
    ),
    "7.01": (
        "Information shared with investors",
        "Information the company makes public to all investors at once under the fair "
        "disclosure rule (Regulation FD), such as presentation slides or a press release.",
    ),
    "8.01": (
        "Other news",
        "Any other event the company considers important to shareholders, reported "
        "voluntarily, such as a share buyback, a lawsuit or a product approval.",
    ),
    "9.01": (
        "Attachments listed",
        "Lists the documents attached to the report, such as a press release, a contract or the "
        "financial statements of an acquired business.",
    ),
    "1": (
        "Change in control",
        _OLD + "someone gained control of the company, such as through a takeover or a large "
        "share purchase.",
    ),
    "2": (
        "Acquisition or sale completed",
        _OLD + "the company completed buying or selling a significant business or assets.",
    ),
    "3": (
        "Bankruptcy or receivership",
        _OLD + "the company or a major subsidiary entered bankruptcy or receivership; "
        "shareholders are paid last, after lenders.",
    ),
    "4": (
        "Auditor changed",
        _OLD + "the company's outside auditor resigned, was dismissed or was replaced.",
    ),
    "5": (
        "Other events",
        _OLD + "any other event the company considered important, such as news releases, deals "
        "or financings.",
    ),
    "6": (
        "Director resigned",
        _OLD + "a director resigned over a disagreement with the company and asked for it to be "
        "disclosed.",
    ),
    "7": (
        "Attachments and financials",
        _OLD + "lists attached documents, such as press releases, and the financial statements "
        "of an acquired business.",
    ),
    "8": (
        "Fiscal year changed",
        _OLD + "the company changed the end date of its fiscal (accounting) year.",
    ),
    "9": (
        "Information shared with investors",
        _OLD + "information made public to all investors at once (Regulation FD). Before late "
        "2000 this item reported shares sold abroad (Regulation S).",
    ),
    "10": (
        "Code of ethics changed",
        _OLD_2003 + "the company changed its code of ethics or waived it for a top officer.",
    ),
    "11": (
        "Employee plan trading halt",
        _OLD_2003 + "employees temporarily could not trade company shares in their retirement "
        "plan (a blackout), so insiders could not either.",
    ),
    "12": (
        "Results announced",
        _OLD_2003 + "the company released its quarterly or annual results.",
    ),
    "13": (
        "Item not on the old form",
        "Not an item of the old 8-K (numbered 1 to 12 until August 2004), probably a labelling "
        "error; open the filing to see what it reports.",
    ),
}

_DILUTION_ITEMS = frozenset({"3.02"})

_ITEM_PREFIX = re.compile(r"^item\s*", re.IGNORECASE)


def describe_form(form: str | None) -> dict[str, str | bool]:
    """Name, explanation, kind and dilution flag of an SEC form code such as "10-Q" or "S-1/A".

    Never raises: an unknown code gets kind "other", the name "SEC form <code>" and a general
    description. An amendment ("/A") gets its base form's entry, named "Amendment: <name>".
    """
    code = " ".join(str(form if form is not None else "").split()).upper()
    amendment = len(code) > 2 and code.endswith("/A")
    entry = _form_entry(code[:-2].rstrip() if amendment else code)
    return {
        "code": code,
        "name": f"Amendment: {entry.name}" if amendment else entry.name,
        "description": entry.description,
        "kind": entry.kind,
        "amendment": amendment,
        "dilution_signal": entry.dilution_signal,
    }


def describe_items(items: str | list[str] | tuple[str, ...] | None) -> list[dict[str, str | bool]]:
    """Each 8-K item of a comma-separated string such as "2.02,9.01", in the given order.

    Spaces, empty parts, an "Item" prefix and repeats are ignored; None or "" gives []. Never
    raises: an unknown item number gets a general entry.
    """
    if not items:
        return []
    text = ",".join(map(str, items)) if isinstance(items, list | tuple) else str(items)
    described = []
    seen = set()
    for part in re.split(r"[,;]", text):
        item = _ITEM_PREFIX.sub("", part.strip()).strip()
        if not item or item in seen:
            continue
        seen.add(item)
        name, description = _ITEMS.get(item, (UNKNOWN_ITEM_NAME, UNKNOWN_ITEM_DESCRIPTION))
        described.append(
            {
                "item": item,
                "name": name,
                "description": description,
                "dilution_signal": item in _DILUTION_ITEMS,
            }
        )
    return described


def _form_entry(code: str) -> _Entry:
    code = _ALIASES.get(code, code)
    if code in _FORMS:
        return _FORMS[code]
    for pattern, entry in _FAMILIES:
        if pattern.fullmatch(code):
            return entry
    return _Entry("other", f"SEC form {code}" if code else "SEC filing", UNKNOWN_FORM_DESCRIPTION)
