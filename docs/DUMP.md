# DUMP MD HACKMIDWEST 2026
## Challenge
### Akamai
The challenge: build a working AI-powered application on Akamai Cloud that solves a real-world problem and goes beyond a basic chatbot. Participants will create an Akamai Cloud (Linode) account and receive $300 in cloud credits to build their solutions. We’ll also provide hosted AI inference to help teams get started, with the option to bring your own inference (BYOI). Teams can combine AI with available Akamai Cloud resources—including compute, storage, databases, networking, Kubernetes, and more—to build and scale their ideas.

Judging Criteria: Projects will be evaluated across four areas:


1) Impact & Usefulness: Are you solving a real problem that people or businesses actually care about?

2) Powered by Akamai: Did you use available Akamai Cloud resources and/or AI inference in your application ?

3) Technical Execution: Does the app actually work? Is the code solid and stable?

4) Creativity & Innovation: Does the project showcase creativity/ originality in its idea, execution, or presentation?
Resources:
[Sign-up link for Akamai Cloud with $300 credits](https://login.linode.com/signup?promo=akm-dev-hack-mid-300-100826-K277)

[HackMidwest x Akamai Cloud Starter Kit](https://github.com/akamai-developers/akamai-workshop-hackmidwest) — Your go-to GitHub resource for the hackathon; quick-start guides using the provided AI inference endpoints and provisioning resources on Akamai Cloud.

[Akamai Cloud Documentation](https://techdocs.akamai.com/cloud-computing/docs/welcome) — Find product documentation, API references, and tutorials for using Akamai Cloud services.
Join our Discord “Edge Case” — Stay connected with our developer community, collaborate, and discuss everything from AI agents and WebAssembly to cloud-native and serverless projects.

Additional information about the hosted AI inference endpoint, available models, API access, and credentials will be provided during the hackathon kickoff.

### Flex
Best FinTech App In this challenge, you are invited to create an innovative idea that pushes the boundaries of technology with FinTech! Develop an application that integrates FinTech in your project.

We're looking for creativity, innovation and technical prowess.

Judging Criteria:

Does the project leverage FinTech? Did you build something unique and innovative and/or utilize FinTech in a creative way?

### AWS (Strands SDK)
Best Use of Strands Agents SDK: In this challenge, you are invited to harness the power of Strands Agents SDK to create innovative, intelligent agents that push the boundaries of what's possible with AI. Strands Agents is an open-source Python SDK for building extensible production-ready AI agents.

Your task is to develop an application that leverages Strands Agents SDK to create agents that can solve complex problems, automate workflows, or enhance user experiences in creative ways. Build agents that can reason, use tools, access data sources, and execute actions to accomplish tasks that would normally require human intelligence.

We're looking for creative implementations that showcase the unique capabilities of Strands Agents SDK to solve real-world problems.

Judging Criteria:

Does the project integrate Strands Agents SDK?

Did you build something unique and innovative and/or utilize Strands Agents in a creative way?
Resources:
[Github Repository](https://github.com/strands-agents/harness-sdk)
[Docs](https://strandsagents.com/)    
[Getting started](https://strandsagents.com/docs/user-guide/sdk/quickstart/overview/)
[Strands Agents Samples](https://github.com/strands-agents/samples)

### DevRev (Computer challenge)
Build a reusable skill or MCP connector in DevRev Computer that solves a real enterprise workflow using the provided Enterprise-Bench dataset, and demonstrate that another authorized teammate can use it to produce a useful, evidence-backed result.

1. For resources and details, go [here](https://hack-midwest-computer-challenge.vercel.app/)

2. Register for challenge [here](https://docs.google.com/forms/d/e/1FAIpQLScAbUnZ58Hw9GLkZxnLmtWCRE-aJHI52YoI4aWq7xa9Ux5jTg/viewform) (link taken from the challenge page)

The details below were read from the challenge page on 2026-10-10 and are summarized, not quoted. Check the page for anything that matters.

Build paths:

1) Reusable skill: package a repeatable workflow with when to use it, required inputs, tools, and expected output.

2) MCP connector: connect Computer to an external tool or sandbox service. The connection must enable a completed workflow, not just exist.

3) Wildcard: an end-to-end automation using agents, workflows, MCP, and DevRev data objects, from intake to a recorded outcome.

Data boundary:

Use only the provided Enterprise-Bench synthetic dataset as business evidence. Connectors may serve that data or carry approved outputs into a sandbox tool. Do not add real customer data, custom company datasets, or live external enrichment.

Starting-point problems suggested on the page:

Sales data quality enhancer; customer trust signals; commitment-to-action connector; customer impact investigator.

What judges look for (the page gives no weights):

1) A useful business outcome beyond a generic chat prompt.

2) Reuse: parameterized inputs, and a demo with another authorized colleague and different records.

3) Evidence and honest limits: inspectable claims, handling of missing or ambiguous data.

4) Safe execution: respect permissions, keep credentials out of code, preview and approve sandbox writes, handle errors and duplicates.

Read-only builds are welcome; more integrations or write actions do not automatically score higher.

Access:

Registration is a request for access, not an instant login. DevRev sends playground setup and kickoff details separately. Do not put passwords or access tokens in the form. Use a personal playground access token and keep it out of chat, source code, and shared files.

Not stated on the page: prizes, deadlines, submission steps, and judging weights.

Resources:
[Challenge page](https://hack-midwest-computer-challenge.vercel.app/) (also hosts the builder skill pack, builder guide, and MCP starter downloads)
[Enterprise-Bench dataset](https://github.com/devrev/enterprise-bench)
[DevRev API specs and plugin guides](https://developer.devrev.ai/about/for-developers)

## Idea: problem, target user, proposed solution, what makes it compelling
We’re building a fintech app for Hack Midwest that gathers financial information from the web and combines it with historical trends and quantitative analysis to generate stock buy, sell, or hold predictions.

The project builds on Hemanth’s original repository, which contains the web-scraping and quantitative-analysis foundations.

This project is compelling because it will hold all 3rd party news source data in one spot for quick and easy information to guide important financial decisions.
Proposed architecture
The backend will use AWS Strands to coordinate agents and connect them to external tools through MCP.

1) News collection and tagging
An agent will gather news articles from sources such as The Wall Street Journal, Bloomberg, and Yahoo Finance, building on the scraping approach in Hemanth’s repository.

Articles will include their original category tags. The agent may add additional tags to support search and analysis.

2) Information storage and retrieval
The collected information will be stored in a backend vector database. A retrieval-augmented generation (RAG) process will make relevant articles available to downstream agents.

3) Quantitative analysis
A math agent will analyze the retrieved information alongside historical and market data. It will produce quantitative signals, supporting information, and graphs, building on the analysis in Hemanth’s repository.

4) Buy, sell, or hold decision
A decision agent will use MCP to connect with JEV. It will receive the math agent’s results and return a categorical decision, such as buy, sell, or hold.

JEV is intended for quick, low-cost tasks such as categorical decisions, yes/no answers, and scoring. 
5) Portfolio context
A portfolio agent will connect to users’ investment accounts through MCP, potentially including Robinhood and Schwab. It will retrieve current holdings so the system can consider the user’s portfolio when providing analysis.

## Demo: the exact interaction you want judges to see
User onboarding
The user logs in.
The user connects a stock account.
The chatbot asks initial questions about the user’s goals, investment amount, risk level, and other relevant preferences.
Store the user’s answers as context.
Include any relevant pre-existing information.
The user can update their goals and context on a settings page.
The AI uses the available information to provide personalized analysis:
Show information about stocks and industries relevant to the user’s interests.
Analyze stocks the user currently holds, including performance and expected outcomes based on available information.

Chatbot
The chatbot should:

Provide feedback on stocks, including a score from 0 to 100 to indicate whether a stock may be a buy or not.
Update the user’s context when they change their goals in chat, and tell them when the update is complete.
Accept pasted news articles and social media information, such as Twitter posts, as additional context.

Home page
The home page should:

Show the user’s current stocks, with relevant figures and recommendations for each.
Show recommended stocks based on the user’s context.
Show general stock recommendations.

Individual stock page
Each stock should have a detail page with:

Short-term volatility charts, including 2-day and 3-day views.
Relevant statistics.
A standard market chart.
Related information gathered from web scraping.

## Team: people, skills, ownership, availability
Allen:
observability, infrastructure + database. Mainly working on akamai work (deployment) and vector database for holding the sources

Jet:
Jev work for decision making. Orchestrating backend with strands. MCP server connections.

Cai:
Web scraping and analysis of sources

Hemanth:
Updating and integrating current project state for baseline, frontend ui/ux to build off of

## Constraints: required tech, APIs, data, budget, deployment, privacy
Strands Agents SDK for python agentic flow, akamai servers for dpeloyment / infrence api, python backend, typescript + nextjs frontend, jev for integrating classification of resources

## Current state: repo, existing code, assets, links, decisions already made
Repo summary for building a prediction product (hemanthsrp/vol-surface-builder) -- basis for project
This repository is a Python tool for turning equity option data into implied volatility surfaces. Its strongest reusable idea is a modular pipeline: acquire data, normalize and filter it, derive analytical features, then expose them through summaries and visualizations. It does not currently aggregate news, collect people’s picks, or predict stock prices.

What the repo contains
src/data_feed.py (src/data_feed.py) retrieves option chains from Yahoo Finance via yfinance, or generates offline synthetic data. Live data is filtered by moneyness and liquidity, then option prices are converted to implied volatility.
src/black_scholes.py (src/black_scholes.py) implements Black–Scholes pricing, Greeks, and implied-volatility inversion using Brent’s method.
src/svi_calibration.py (src/svi_calibration.py) generates synthetic volatility data and fits SVI parameters to observed volatility slices.
src/surface_builder.py (src/surface_builder.py) interpolates scattered observations onto a regular strike/maturity grid, with nearest-neighbor fallback and optional smoothing. It also extracts maturity slices and computes summary statistics.
src/visualization.py (src/visualization.py) creates static and interactive charts.
src/config.py (src/config.py) holds shared defaults, filters, model parameters, and output paths.
main.py (main.py) runs the pipeline from the command line and saves charts and a CSV.
tests/ covers option pricing, SVI, and surface construction.

The standard data exchange is a pandas DataFrame plus spot price. The live option rows include fields such as strike, T, iv, moneyness, log_moneyness, expiry, option_type, oi, and volume. 
How this can inform the new product
Reuse the separation of concerns, not the volatility-specific calculations as a price-prediction model.

A product built around aggregated news, Yahoo Finance, and people’s picks could follow a similar flow:

Ingest sources: collect news articles, market data, and user picks through separate adapters.
Normalize records: map each source into stable schemas with timestamps, symbols, source IDs, and provenance.
Validate and filter: handle duplicates, stale data, malformed records, missing values, and low-quality inputs.
Derive features: calculate market indicators, summarize article content and sentiment, and measure pick activity or track records.
Combine evidence: produce a prediction with a time horizon, confidence or uncertainty, and an explanation of which signals contributed.
Present and persist: provide summaries, charts, and stored historical predictions so outcomes can be evaluated later.

The repository’s data_feed.py is a useful pattern for source adapters, its standardized DataFrame is a pattern for normalized records, and compute_surface_statistics is a small example of turning raw inputs into product-facing metrics. The interpolation and Black–Scholes modules are specific to options analytics and should only carry over if options-derived signals are part of the product.

The primary gap is:
The current statistics are volatility-surface diagnostics, not measures of predictive accuracy. A prediction product would need historical snapshots, outcome labels, and evaluation by horizon and source.
Data provenance and timing matter: store when each article, quote, and pick was observed, so predictions can be reconstructed without accidentally using information that arrived later.

## Uncertainties: questions, risks, and ideas you haven’t committed to
feasbility personal finance management connection (robinhood mcp), what models to utilize around the stack (chatbot, rag, etc)