# NBA Injury Source Notes

## Breakthrough
The official NBA injury-report page can be scraped for the latest PDF link.

Working discovery path:
- Official page: `https://official.nba.com/nba-injury-report-2025-26-season/`
- Latest PDF discovery now works in-code via browser-like headers and PDF-link extraction.

Confirmed discovered live example:
- `https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-03-31_03_45PM.pdf`

## What this means
- We now have a real official-source discovery path for the latest NBA injury report.
- The next step is parsing the PDF into structured rows and then mapping rows to teams/players/statuses for the bot.

## Earlier tested sources
1. ESPN team injury endpoint
- reachable, but returned empty `{}` for tested teams.

2. ESPN scoreboard feed
- useful for game/team/stat context, but no direct injury list found in tested competitor objects.

3. Basketball-Reference injury page
- readable through lightweight fetch preview, but direct bot requests hit Cloudflare and were not stable enough for live use.

## Best next step
1. Download latest official NBA PDF
2. Parse rows from PDF text/table structure
3. Aggregate injury burden by team
4. Feed that into the NBA weighted model
