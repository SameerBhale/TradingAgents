from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph

# DEFAULT_CONFIG already applies TRADINGAGENTS_* env-var overrides
# (llm_provider, deep_think_llm, quick_think_llm, backend_url, etc.),
# so users can switch models or endpoints purely via .env without
# editing this script. Override individual keys here only when you
# want a hard-coded value that should ignore the environment.
config = DEFAULT_CONFIG.copy()

# Initialize with custom config
ta = TradingAgentsGraph(debug=True, config=config)

# The default market is India (TRADINGAGENTS_MARKET=india): pass an NSE symbol
# (RELIANCE, TCS.NS), a BSE listing (RELIANCE.BO) or an index (NIFTY). Dates are
# trading days on the IST clock; a run dated today reads the live price until the
# session settles at ~16:00 IST.
_, decision = ta.propagate("RELIANCE", "2026-09-01")
print(decision)
