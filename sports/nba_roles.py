from __future__ import annotations

STAR_PLAYERS = {
    "Giannis Antetokounmpo", "Franz Wagner", "Brandon Ingram", "RJ Barrett", "Kyrie Irving",
    "Fred VanVleet", "Anthony Black", "Jonathan Isaac", "Miles McBride", "P.J. Washington",
    "Klay Thompson", "Mark Williams", "Jalen Duren", "Tobias Harris", "Cade Cunningham",
}


def player_importance_weight(player_name: str):
    if player_name in STAR_PLAYERS:
        return 2.0
    return 1.0
