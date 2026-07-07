from __future__ import annotations

from dataclasses import dataclass

from bot.showdown_config import OWNED_BATTLE_FORMAT

SINGLES_BATTLE_KIND = "singles"
DOUBLES_BATTLE_KIND = "doubles"
FREEFORALL_BATTLE_KIND = "freeforall"
MULTI_RANDOM_BATTLE_FORMAT_ID = "gen9multirandombattle"

OWNED_MODE = "owned"
RANDOM_MODE = "random"


@dataclass(frozen=True)
class ChallengeFormatOption:
    key: str
    format_id: str
    label: str
    short_label: str


FORMAT_OPTIONS: dict[str, dict[str, tuple[ChallengeFormatOption, ...]]] = {
    SINGLES_BATTLE_KIND: {
        OWNED_MODE: (
            ChallengeFormatOption("competitive", OWNED_BATTLE_FORMAT, "Competitive", "COMP"),
            ChallengeFormatOption("ou", "gen9ou", "OU", "OU"),
            ChallengeFormatOption("uu", "gen9uu", "UU", "UU"),
            ChallengeFormatOption("ru", "gen9ru", "RU", "RU"),
            ChallengeFormatOption("nu", "gen9nu", "NU", "NU"),
            ChallengeFormatOption("pu", "gen9pu", "PU", "PU"),
            ChallengeFormatOption("zu", "gen9zu", "ZU", "ZU"),
            ChallengeFormatOption("ubers", "gen9ubers", "Ubers", "UBR"),
            ChallengeFormatOption("ag", "gen9anythinggoes", "Anything Goes", "AG"),
            ChallengeFormatOption("lc", "gen9lc", "Little Cup", "LC"),
            ChallengeFormatOption("monotype", "gen9monotype", "Monotype", "MONO"),
            ChallengeFormatOption("cap", "gen9cap", "CAP", "CAP"),
            ChallengeFormatOption("nfe", "gen9nfe", "NFE", "NFE"),
        ),
        RANDOM_MODE: (
            ChallengeFormatOption("randombattle", "gen9randombattle", "Random Battle", "RAND"),
            ChallengeFormatOption("gen8randombattle", "gen8randombattle", "Gen 8 Random Battle", "G8"),
            ChallengeFormatOption("gen7randombattle", "gen7randombattle", "Gen 7 Random Battle", "G7"),
            ChallengeFormatOption("gen6randombattle", "gen6randombattle", "Gen 6 Random Battle", "G6"),
            ChallengeFormatOption("gen5randombattle", "gen5randombattle", "Gen 5 Random Battle", "G5"),
            ChallengeFormatOption("gen4randombattle", "gen4randombattle", "Gen 4 Random Battle", "G4"),
            ChallengeFormatOption("gen3randombattle", "gen3randombattle", "Gen 3 Random Battle", "G3"),
            ChallengeFormatOption("gen2randombattle", "gen2randombattle", "Gen 2 Random Battle", "G2"),
            ChallengeFormatOption("gen1randombattle", "gen1randombattle", "Gen 1 Random Battle", "G1"),
            ChallengeFormatOption("battlefactory", "gen9battlefactory", "Battle Factory", "FACT"),
            ChallengeFormatOption("hackmonscup", "gen9hackmonscup", "Hackmons Cup", "HCUP"),
            ChallengeFormatOption("challengecup", "gen9challengecup6v6", "Challenge Cup", "CCUP"),
            ChallengeFormatOption("monotyperandom", "gen9monotyperandombattle", "Monotype Random Battle", "MRND"),
            ChallengeFormatOption("randomroulette", "gen9randomroulette", "Random Roulette", "RLT"),
            ChallengeFormatOption("babyrandom", "gen9babyrandombattle", "Baby Random Battle", "BABY"),
            ChallengeFormatOption("godlygift", "gen9godlygiftrandombattle", "Godly Gift Random Battle", "GIFT"),
        ),
    },
    DOUBLES_BATTLE_KIND: {
        OWNED_MODE: (
            ChallengeFormatOption("doublescustom", "gen9doublescustomgame", "Owner Team Doubles", "CSTM"),
            ChallengeFormatOption("doublesou", "gen9doublesou", "Doubles OU", "DOU"),
            ChallengeFormatOption("vgc", "gen9vgc2026regi", "VGC 2026 Reg I", "VGC"),
            ChallengeFormatOption("2v2", "gen92v2doubles", "2v2 Doubles", "2V2"),
        ),
        RANDOM_MODE: (
            ChallengeFormatOption("randomdoubles", "gen9randomdoublesbattle", "Random Doubles Battle", "RAND"),
            ChallengeFormatOption("gen8randomdoubles", "gen8randomdoublesbattle", "Gen 8 Random Doubles Battle", "G8RD"),
            ChallengeFormatOption("doubleshackmonscup", "gen9doubleshackmonscup", "Doubles Hackmons Cup", "DHC"),
            ChallengeFormatOption("challengecup2v2", "gen9challengecup2v2", "Challenge Cup 2v2", "CC2V"),
        ),
    },
    FREEFORALL_BATTLE_KIND: {
        OWNED_MODE: (
            ChallengeFormatOption("freeforall", "gen9freeforall", "Free-For-All", "FFA"),
        ),
        RANDOM_MODE: (
            ChallengeFormatOption("freeforallrandom", "gen9freeforallrandombattle", "Free-For-All Random Battle", "RFFA"),
            ChallengeFormatOption("multirandom", MULTI_RANDOM_BATTLE_FORMAT_ID, "Multi Random Battle", "MULTI"),
        ),
    },
}


def normalize_battle_kind(value: str | None) -> str:
    kind = str(value or "").strip().lower()
    if kind in FORMAT_OPTIONS:
        return kind
    return SINGLES_BATTLE_KIND


def normalize_mode(value: str | None, *, battle_kind: str) -> str:
    kind = normalize_battle_kind(battle_kind)
    mode = str(value or "").strip().lower()
    if mode in FORMAT_OPTIONS[kind]:
        return mode
    return RANDOM_MODE if kind == DOUBLES_BATTLE_KIND else OWNED_MODE


def format_options_for(battle_kind: str, mode: str) -> tuple[ChallengeFormatOption, ...]:
    kind = normalize_battle_kind(battle_kind)
    normalized_mode = normalize_mode(mode, battle_kind=kind)
    return FORMAT_OPTIONS[kind][normalized_mode]


def default_format_option(battle_kind: str, mode: str) -> ChallengeFormatOption:
    return format_options_for(battle_kind, mode)[0]


def resolve_format_option(battle_kind: str, mode: str, format_key: str | None) -> ChallengeFormatOption:
    for option in format_options_for(battle_kind, mode):
        if option.key == str(format_key or "").strip().lower():
            return option
    return default_format_option(battle_kind, mode)
