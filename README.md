# SQL Agent

Query sports schedules using natural language. Data source: [My sports schedule data on Dolthub](https://www.dolthub.com/repositories/gmichnikov/sports-schedules)

## Setup

```bash
pip install -r requirements.txt
echo "API_KEY=your_anthropic_api_key" > .env
```

## Usage

```bash
python3 script.py "Find all baseball games on Friday"
python3 script.py "Show me games in New York this week"
python3 script.py "What games are happening today?"
```

## Examples

For complex queries that require planning or analysis, use the `--agent` flag

See [EXAMPLES.md](EXAMPLES.md) for a detailed example.

## Output

The script generates SQL, executes it against the DoltHub database, and provides both raw results and a clean summary of games in the format:

```
• Friday 2024-04-05 Hartford @ Portland
• Friday 2024-04-05 New Hampshire @ Binghamton
```
