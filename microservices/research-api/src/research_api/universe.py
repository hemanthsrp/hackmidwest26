"""The stocks offered for each industry.

A curated, committed list: 24 large US-listed companies per GICS sector, in rough
market-cap order within the sector. It is a starting universe for the demo, not a
screen or a recommendation, and it is dated because index membership drifts
(mergers, delistings, ticker changes). Review it before a demo; a test keeps it
well-formed (24 per sector, unique, valid tickers) but cannot tell whether a
company still trades.
"""

UNIVERSE_AS_OF = "2026-10-11"
STOCKS_PER_INDUSTRY = 24

# slug -> (display name, [(ticker, company name), ...])
INDUSTRIES: dict[str, tuple[str, list[tuple[str, str]]]] = {
    "technology": ("Technology", [
        ("AAPL", "Apple"), ("MSFT", "Microsoft"), ("NVDA", "NVIDIA"), ("AVGO", "Broadcom"),
        ("ORCL", "Oracle"), ("CRM", "Salesforce"), ("AMD", "Advanced Micro Devices"), ("ADBE", "Adobe"),
        ("CSCO", "Cisco Systems"), ("ACN", "Accenture"), ("IBM", "IBM"), ("QCOM", "Qualcomm"),
        ("TXN", "Texas Instruments"), ("INTU", "Intuit"), ("NOW", "ServiceNow"), ("AMAT", "Applied Materials"),
        ("MU", "Micron Technology"), ("LRCX", "Lam Research"), ("PANW", "Palo Alto Networks"),
        ("ADI", "Analog Devices"), ("KLAC", "KLA"), ("SNPS", "Synopsys"), ("CDNS", "Cadence Design Systems"),
        ("INTC", "Intel"),
    ]),
    "health-care": ("Health Care", [
        ("LLY", "Eli Lilly"), ("UNH", "UnitedHealth Group"), ("JNJ", "Johnson & Johnson"), ("ABBV", "AbbVie"),
        ("MRK", "Merck"), ("TMO", "Thermo Fisher Scientific"), ("ABT", "Abbott Laboratories"), ("DHR", "Danaher"),
        ("AMGN", "Amgen"), ("ISRG", "Intuitive Surgical"), ("PFE", "Pfizer"), ("BSX", "Boston Scientific"),
        ("SYK", "Stryker"), ("GILD", "Gilead Sciences"), ("VRTX", "Vertex Pharmaceuticals"), ("MDT", "Medtronic"),
        ("BMY", "Bristol-Myers Squibb"), ("REGN", "Regeneron Pharmaceuticals"), ("CVS", "CVS Health"),
        ("ELV", "Elevance Health"), ("CI", "Cigna"), ("ZTS", "Zoetis"), ("MCK", "McKesson"), ("HCA", "HCA Healthcare"),
    ]),
    "financials": ("Financials", [
        ("JPM", "JPMorgan Chase"), ("BAC", "Bank of America"), ("WFC", "Wells Fargo"), ("GS", "Goldman Sachs"),
        ("MS", "Morgan Stanley"), ("C", "Citigroup"), ("V", "Visa"), ("MA", "Mastercard"),
        ("AXP", "American Express"), ("BLK", "BlackRock"), ("SCHW", "Charles Schwab"), ("SPGI", "S&P Global"),
        ("PGR", "Progressive"), ("CB", "Chubb"), ("MMC", "Marsh McLennan"), ("USB", "U.S. Bancorp"),
        ("PNC", "PNC Financial Services"), ("TFC", "Truist Financial"), ("COF", "Capital One"),
        ("ICE", "Intercontinental Exchange"), ("CME", "CME Group"), ("AON", "Aon"), ("MET", "MetLife"),
        ("AIG", "American International Group"),
    ]),
    "consumer-discretionary": ("Consumer Discretionary", [
        ("AMZN", "Amazon"), ("TSLA", "Tesla"), ("HD", "Home Depot"), ("MCD", "McDonald's"),
        ("LOW", "Lowe's"), ("NKE", "Nike"), ("SBUX", "Starbucks"), ("BKNG", "Booking Holdings"),
        ("TJX", "TJX Companies"), ("ORLY", "O'Reilly Automotive"), ("CMG", "Chipotle Mexican Grill"),
        ("MAR", "Marriott International"), ("GM", "General Motors"), ("F", "Ford Motor"), ("HLT", "Hilton"),
        ("AZO", "AutoZone"), ("ROST", "Ross Stores"), ("DHI", "D.R. Horton"), ("LEN", "Lennar"),
        ("YUM", "Yum! Brands"), ("EBAY", "eBay"), ("RCL", "Royal Caribbean"), ("LULU", "Lululemon Athletica"),
        ("ULTA", "Ulta Beauty"),
    ]),
    "communication-services": ("Communication Services", [
        ("GOOGL", "Alphabet"), ("META", "Meta Platforms"), ("NFLX", "Netflix"), ("DIS", "Walt Disney"),
        ("CMCSA", "Comcast"), ("T", "AT&T"), ("VZ", "Verizon"), ("TMUS", "T-Mobile US"),
        ("CHTR", "Charter Communications"), ("EA", "Electronic Arts"), ("TTWO", "Take-Two Interactive"),
        ("WBD", "Warner Bros. Discovery"), ("OMC", "Omnicom"), ("LYV", "Live Nation Entertainment"),
        ("TTD", "The Trade Desk"), ("MTCH", "Match Group"), ("FOXA", "Fox Corporation"), ("NWSA", "News Corp"),
        ("RBLX", "Roblox"), ("PINS", "Pinterest"), ("SNAP", "Snap"), ("ROKU", "Roku"), ("TKO", "TKO Group"),
        ("SPOT", "Spotify"),
    ]),
    "consumer-staples": ("Consumer Staples", [
        ("PG", "Procter & Gamble"), ("KO", "Coca-Cola"), ("PEP", "PepsiCo"), ("COST", "Costco"),
        ("WMT", "Walmart"), ("PM", "Philip Morris International"), ("MDLZ", "Mondelez International"),
        ("MO", "Altria"), ("CL", "Colgate-Palmolive"), ("TGT", "Target"), ("KMB", "Kimberly-Clark"),
        ("GIS", "General Mills"), ("KDP", "Keurig Dr Pepper"), ("SYY", "Sysco"), ("STZ", "Constellation Brands"),
        ("KR", "Kroger"), ("HSY", "Hershey"), ("MNST", "Monster Beverage"), ("KHC", "Kraft Heinz"),
        ("EL", "Estee Lauder"), ("ADM", "Archer-Daniels-Midland"), ("DG", "Dollar General"),
        ("DLTR", "Dollar Tree"), ("CHD", "Church & Dwight"),
    ]),
    "energy": ("Energy", [
        ("XOM", "Exxon Mobil"), ("CVX", "Chevron"), ("COP", "ConocoPhillips"), ("EOG", "EOG Resources"),
        ("SLB", "SLB"), ("WMB", "Williams Companies"), ("MPC", "Marathon Petroleum"), ("PSX", "Phillips 66"),
        ("OKE", "ONEOK"), ("VLO", "Valero Energy"), ("KMI", "Kinder Morgan"), ("OXY", "Occidental Petroleum"),
        ("BKR", "Baker Hughes"), ("HAL", "Halliburton"), ("FANG", "Diamondback Energy"), ("DVN", "Devon Energy"),
        ("TRGP", "Targa Resources"), ("CTRA", "Coterra Energy"), ("EQT", "EQT"), ("TPL", "Texas Pacific Land"),
        ("EXE", "Expand Energy"), ("APA", "APA"), ("LNG", "Cheniere Energy"), ("FTI", "TechnipFMC"),
    ]),
    "industrials": ("Industrials", [
        ("GE", "GE Aerospace"), ("CAT", "Caterpillar"), ("RTX", "RTX"), ("UNP", "Union Pacific"),
        ("HON", "Honeywell"), ("ETN", "Eaton"), ("DE", "Deere & Company"), ("BA", "Boeing"),
        ("LMT", "Lockheed Martin"), ("UPS", "United Parcel Service"), ("ADP", "Automatic Data Processing"),
        ("GEV", "GE Vernova"), ("WM", "Waste Management"), ("PH", "Parker-Hannifin"), ("TT", "Trane Technologies"),
        ("NOC", "Northrop Grumman"), ("GD", "General Dynamics"), ("CSX", "CSX"), ("ITW", "Illinois Tool Works"),
        ("EMR", "Emerson Electric"), ("FDX", "FedEx"), ("MMM", "3M"), ("NSC", "Norfolk Southern"),
        ("CTAS", "Cintas"),
    ]),
    "materials": ("Materials", [
        ("LIN", "Linde"), ("SHW", "Sherwin-Williams"), ("APD", "Air Products"), ("ECL", "Ecolab"),
        ("FCX", "Freeport-McMoRan"), ("NEM", "Newmont"), ("CTVA", "Corteva"), ("DOW", "Dow"),
        ("DD", "DuPont"), ("MLM", "Martin Marietta Materials"), ("VMC", "Vulcan Materials"), ("NUE", "Nucor"),
        ("PPG", "PPG Industries"), ("LYB", "LyondellBasell"), ("IFF", "International Flavors & Fragrances"),
        ("STLD", "Steel Dynamics"), ("BALL", "Ball Corporation"), ("PKG", "Packaging Corporation of America"),
        ("AMCR", "Amcor"), ("CF", "CF Industries"), ("MOS", "Mosaic"), ("ALB", "Albemarle"),
        ("IP", "International Paper"), ("AVY", "Avery Dennison"),
    ]),
    "real-estate": ("Real Estate", [
        ("PLD", "Prologis"), ("AMT", "American Tower"), ("EQIX", "Equinix"), ("WELL", "Welltower"),
        ("SPG", "Simon Property Group"), ("PSA", "Public Storage"), ("O", "Realty Income"),
        ("DLR", "Digital Realty"), ("CCI", "Crown Castle"), ("CBRE", "CBRE Group"), ("VICI", "VICI Properties"),
        ("EXR", "Extra Space Storage"), ("AVB", "AvalonBay Communities"), ("IRM", "Iron Mountain"),
        ("EQR", "Equity Residential"), ("SBAC", "SBA Communications"), ("WY", "Weyerhaeuser"),
        ("VTR", "Ventas"), ("INVH", "Invitation Homes"), ("ARE", "Alexandria Real Estate Equities"),
        ("MAA", "Mid-America Apartment Communities"), ("KIM", "Kimco Realty"), ("ESS", "Essex Property Trust"),
        ("UDR", "UDR"),
    ]),
    "utilities": ("Utilities", [
        ("NEE", "NextEra Energy"), ("SO", "Southern Company"), ("DUK", "Duke Energy"),
        ("CEG", "Constellation Energy"), ("AEP", "American Electric Power"), ("SRE", "Sempra"),
        ("D", "Dominion Energy"), ("EXC", "Exelon"), ("XEL", "Xcel Energy"),
        ("PEG", "Public Service Enterprise Group"), ("ED", "Consolidated Edison"), ("WEC", "WEC Energy Group"),
        ("EIX", "Edison International"), ("ETR", "Entergy"), ("AWK", "American Water Works"), ("DTE", "DTE Energy"),
        ("PPL", "PPL Corporation"), ("FE", "FirstEnergy"), ("AEE", "Ameren"), ("ES", "Eversource Energy"),
        ("CNP", "CenterPoint Energy"), ("ATO", "Atmos Energy"), ("CMS", "CMS Energy"), ("VST", "Vistra"),
    ]),
}
