"""Implements the credibility formula from microservices/scraper-analysis/README.md:

    C = min(1.0, w1*S_domain + w2*S_author + w3*S_consensus - P_noise)

w1+w2+w3 must equal 1.0. Official government filings (SEC, Senate/House
disclosures) are hardcoded to S_domain=1.0 at the normalization stage rather
than passed through this formula -- their credibility is definitional, not
estimated.
"""

DEFAULT_WEIGHTS = (0.5, 0.25, 0.25)  # (domain, author, consensus)


def credibility_score(
    domain_score: float,
    author_score: float,
    consensus_score: float,
    noise_penalty: float = 0.0,
    weights: tuple[float, float, float] = DEFAULT_WEIGHTS,
) -> float:
    w1, w2, w3 = weights
    if round(w1 + w2 + w3, 6) != 1.0:
        raise ValueError("credibility weights must sum to 1.0")
    raw = w1 * domain_score + w2 * author_score + w3 * consensus_score
    return min(1.0, max(0.0, raw - noise_penalty))
