"""Template-based synthetic query generator for MTG oracle text.

Generates short, user-intent-style query strings from normalized oracle text.
These are used as the left side of (query, oracle_text) training pairs so the
model is exposed to asymmetric query-document pairs during fine-tuning, which
is the primary fix for poor short-query retrieval quality.

Usage::

    from ot_backend.embed.query_gen import generate_template_queries
    queries = generate_template_queries(normalized_text)
    # returns e.g. ["draw a card", "card draw", "draw cards effect"]

All patterns are matched against the already-normalized oracle text produced by
``text_prep.normalize_oracle_text``.  Key normalization facts that affect
pattern design:

- Mana symbols are expanded:  ``{T}: Add {G}`` → ``"tap this card: Add one green mana."``
- Card names are replaced:    ``Lightning Bolt deals...`` → ``"this card deals..."``
- Numbers are word-ified:     ``3`` → ``"three"``
- Reminder text is stripped:  ``Flying (...)`` → ``"flying."``
- Case is **not** lowercased: ``"Draw a card"`` keeps its capital D
  → always use ``re.IGNORECASE``
"""

from __future__ import annotations

import re
from typing import NamedTuple

MAX_QUERIES_PER_FACE = 5


class _Rule(NamedTuple):
    pattern: re.Pattern[str]
    queries: tuple[str, ...]


# ---------------------------------------------------------------------------
# Rule table
# ---------------------------------------------------------------------------
# Rules are evaluated in order.  The first MAX_QUERIES_PER_FACE distinct query
# strings collected across all matching rules are returned.
#
# Query strings should be short (2–8 words), lowercase, and phrased the way a
# real user would type them into a search box.
# ---------------------------------------------------------------------------

_I = re.IGNORECASE

_RULES: tuple[_Rule, ...] = (
    # ------------------------------------------------------------------
    # Card draw
    # ------------------------------------------------------------------
    _Rule(
        re.compile(r"\bdraw (?:a|an extra|two|three|four|five) cards?\b", _I),
        ("draw a card", "card draw", "draw cards"),
    ),
    _Rule(
        re.compile(r"\b(?:target player|each player|each opponent) draws? (?:a|two|three|four) cards?\b", _I),
        ("draw cards", "symmetric draw", "force draw"),
    ),
    _Rule(
        re.compile(r"\bdraw (?:cards? )?(?:at the beginning|each turn|for each)\b", _I),
        ("repeatable card draw", "draw cards each turn"),
    ),
    # ------------------------------------------------------------------
    # Discard
    # ------------------------------------------------------------------
    _Rule(
        re.compile(r"\bdiscard (?:a|two|three|your hand|that card)\b", _I),
        ("discard cards", "hand disruption"),
    ),
    _Rule(
        re.compile(r"\beach opponent discards\b", _I),
        ("make opponents discard", "hand disruption", "discard effect"),
    ),
    # ------------------------------------------------------------------
    # Counterspells
    # ------------------------------------------------------------------
    _Rule(
        re.compile(r"\bcounter target spell\b", _I),
        ("counterspell", "counter a spell", "counter magic"),
    ),
    _Rule(
        re.compile(r"\bcounter target spell unless (?:its controller pays|they pay)\b", _I),
        ("soft counter", "conditional counterspell", "tax counter"),
    ),
    _Rule(
        re.compile(r"\bcounter target (?:creature|artifact|enchantment) spell\b", _I),
        ("counter permanent spell", "counter specific spell type"),
    ),
    # ------------------------------------------------------------------
    # Creature removal — destroy
    # ------------------------------------------------------------------
    _Rule(
        re.compile(r"\bdestroy target (?:\w+ )*creature\b", _I),
        ("destroy creature", "creature removal", "kill creature"),
    ),
    _Rule(
        re.compile(r"\bdestroy target (?:\w+ )*(?:artifact|enchantment)\b", _I),
        ("destroy artifact", "destroy enchantment", "artifact removal"),
    ),
    _Rule(
        re.compile(r"\bdestroy all creatures\b", _I),
        ("destroy all creatures", "board wipe", "wrath effect"),
    ),
    _Rule(
        re.compile(r"\bdestroy all (?:\w+ )*permanents\b", _I),
        ("destroy all permanents", "total board wipe"),
    ),
    # ------------------------------------------------------------------
    # Removal — exile
    # ------------------------------------------------------------------
    _Rule(
        re.compile(r"\bexile target (?:\w+ )*creature\b", _I),
        ("exile creature", "exile removal"),
    ),
    _Rule(
        re.compile(r"\bexile target (?:\w+ )*(?:artifact|enchantment|permanent)\b", _I),
        ("exile permanent", "exile artifact"),
    ),
    _Rule(
        re.compile(r"\bexile all\b", _I),
        ("exile all", "mass exile"),
    ),
    # ------------------------------------------------------------------
    # Damage — direct burn
    # ------------------------------------------------------------------
    _Rule(
        re.compile(r"\bdeals? (?:\w+ )?damage to any target\b", _I),
        ("burn spell", "direct damage", "deal damage to any target"),
    ),
    _Rule(
        re.compile(r"\bdeals? (?:\w+ )?damage to (?:each|all) (?:creatures?|players?|opponents?|permanents?)\b", _I),
        ("damage to all", "sweeper damage", "deal damage to all"),
    ),
    _Rule(
        re.compile(r"\bdeals? (?:\w+ )?damage to target (?:player|opponent)\b", _I),
        ("burn player", "deal damage to player", "direct damage"),
    ),
    _Rule(
        re.compile(r"\bdeals? (?:\w+ )?damage to target (?:\w+ )?creature\b", _I),
        ("burn creature", "deal damage to creature", "targeted damage"),
    ),
    # ------------------------------------------------------------------
    # Mana production
    # ------------------------------------------------------------------
    _Rule(
        re.compile(r"\btap this card: Add one green mana\b", _I),
        ("tap for green mana", "mana dork", "mana elf", "green mana producer"),
    ),
    _Rule(
        re.compile(r"\btap this card: Add one (?:white|blue|black|red) mana\b", _I),
        ("tap for colored mana", "mana creature"),
    ),
    _Rule(
        re.compile(r"\btap this card: Add (?:two|three|four) colorless mana\b", _I),
        ("colorless mana rock", "tap for colorless mana", "mana rock"),
    ),
    _Rule(
        re.compile(r"\btap this card: Add one colorless mana\b", _I),
        ("colorless mana rock", "tap for mana"),
    ),
    _Rule(
        re.compile(r"\btap this card: Add (?:two|three|four)\b", _I),
        ("produce multiple mana", "mana ramp", "mana acceleration"),
    ),
    _Rule(
        re.compile(r"\btap this card: Add.*mana of any color\b", _I),
        ("any color mana", "color fixing", "rainbow mana"),
    ),
    _Rule(
        re.compile(r"\bAdd (?:\w+ )*mana to your mana pool\b", _I),
        ("add mana", "mana ramp"),
    ),
    # ------------------------------------------------------------------
    # Life gain
    # ------------------------------------------------------------------
    _Rule(
        re.compile(r"\byou gain (?:\w+) life\b", _I),
        ("gain life", "life gain"),
    ),
    _Rule(
        re.compile(r"\bgain (?:\w+) life (?:for each|whenever|at the beginning)\b", _I),
        ("repeatable life gain", "gain life each trigger"),
    ),
    # ------------------------------------------------------------------
    # Life loss / drain
    # ------------------------------------------------------------------
    _Rule(
        re.compile(r"\b(?:each opponent|target player|target opponent|each player) loses (?:\w+) life\b", _I),
        ("opponent loses life", "drain life", "life loss effect"),
    ),
    _Rule(
        re.compile(r"\bgain (?:\w+) life and (?:target player|each opponent|they) loses? (?:\w+) life\b", _I),
        ("drain life", "life drain", "gain and drain"),
    ),
    # ------------------------------------------------------------------
    # Punish opponent for drawing
    # ------------------------------------------------------------------
    _Rule(
        re.compile(r"\bwhenever (?:a player|an opponent|target player) draws? (?:a|their (?:first|second)) card\b", _I),
        ("punish drawing cards", "opponent draws trigger", "draw punishment"),
    ),
    # ------------------------------------------------------------------
    # Bounce
    # ------------------------------------------------------------------
    _Rule(
        re.compile(r"\breturn target (?:\w+ )*(?:creature|permanent|card) to its owner.?s hand\b", _I),
        ("bounce effect", "return to hand", "tempo removal"),
    ),
    _Rule(
        re.compile(r"\breturn target (?:\w+ )*(?:creature|permanent) to (?:its owner.?s hand|your hand)\b", _I),
        ("bounce", "return to hand"),
    ),
    # ------------------------------------------------------------------
    # Tutor / library search
    # ------------------------------------------------------------------
    _Rule(
        re.compile(r"\bsearch your library for (?:a|an) (?:\w+ )*(?:basic )?land\b", _I),
        ("land tutor", "fetch land", "search for land", "ramp spell"),
    ),
    _Rule(
        re.compile(r"\bsearch your library for (?:a|an) (?:\w+ )*creature\b", _I),
        ("creature tutor", "search for creature"),
    ),
    _Rule(
        re.compile(r"\bsearch your library for (?:a|an) (?:\w+ )*card\b", _I),
        ("tutor", "search library", "find any card"),
    ),
    # ------------------------------------------------------------------
    # Reanimation
    # ------------------------------------------------------------------
    _Rule(
        re.compile(r"\breturn (?:target )?(?:\w+ )*creature card from (?:your|a|their) graveyard\b", _I),
        ("reanimate creature", "return from graveyard", "graveyard recursion"),
    ),
    _Rule(
        re.compile(r"\bput (?:target )?(?:\w+ )*creature card from (?:your|a) graveyard onto the battlefield\b", _I),
        ("reanimate", "graveyard to battlefield"),
    ),
    # ------------------------------------------------------------------
    # Mill
    # ------------------------------------------------------------------
    _Rule(
        re.compile(r"\bput the top (?:\w+) cards? of (?:your|a|target player.?s) library into (?:your|their|a|the) graveyard\b", _I),
        ("mill cards", "library mill", "put cards in graveyard"),
    ),
    _Rule(
        re.compile(r"\bmills? (?:\w+) cards?\b", _I),
        ("mill", "mill cards"),
    ),
    # ------------------------------------------------------------------
    # Token creation
    # ------------------------------------------------------------------
    _Rule(
        re.compile(r"\bcreate (?:a|an|one|two|three|four|five) .{3,60}?tokens?\b", _I),
        ("create tokens", "token generation", "make tokens"),
    ),
    # ------------------------------------------------------------------
    # +1/+1 counters (normalized P/T form: "plus one strength and plus one toughness")
    # ------------------------------------------------------------------
    _Rule(
        re.compile(r"\bplus (?:one|two|three) strength and plus (?:one|two|three) toughness\b", _I),
        ("put plus one plus one counters", "grow creature", "strengthen creature"),
    ),
    _Rule(
        re.compile(r"\bput (?:\w+) (?:\+1/\+1|counter) counters? on\b", _I),
        ("put counters on creature", "counter manipulation"),
    ),
    # ------------------------------------------------------------------
    # Triggered abilities — death
    # ------------------------------------------------------------------
    _Rule(
        re.compile(r"\bwhenever (?:a|\w+) creature (?:you control )?dies\b", _I),
        ("creature death trigger", "when creature dies", "death trigger"),
    ),
    # ------------------------------------------------------------------
    # Triggered abilities — ETB
    # ------------------------------------------------------------------
    _Rule(
        re.compile(r"\bwhen(?:ever)? (?:this card|a creature|another creature) enters the battlefield\b", _I),
        ("enters the battlefield effect", "etb trigger", "when creature enters"),
    ),
    # ------------------------------------------------------------------
    # Triggered abilities — upkeep / end step
    # ------------------------------------------------------------------
    _Rule(
        re.compile(r"\bat the beginning of (?:your|each) upkeep\b", _I),
        ("upkeep trigger", "trigger each upkeep"),
    ),
    _Rule(
        re.compile(r"\bat the beginning of (?:your|each) end step\b", _I),
        ("end step trigger", "trigger each turn"),
    ),
    # ------------------------------------------------------------------
    # Sacrifice
    # ------------------------------------------------------------------
    _Rule(
        re.compile(r"\bsacrifice (?:a|another|target) creature\b", _I),
        ("sacrifice creature", "sac outlet", "sacrifice fodder"),
    ),
    _Rule(
        re.compile(r"\bsacrifice this card\b", _I),
        ("sacrifice self", "one time use"),
    ),
    # ------------------------------------------------------------------
    # Copy spells
    # ------------------------------------------------------------------
    _Rule(
        re.compile(r"\bcopy target (?:\w+ )*spell\b", _I),
        ("copy a spell", "fork effect", "spell copying"),
    ),
    # ------------------------------------------------------------------
    # Control — steal permanent
    # ------------------------------------------------------------------
    _Rule(
        re.compile(r"\bgain control of target (?:\w+ )*(?:creature|permanent|artifact)\b", _I),
        ("steal creature", "gain control", "take control of permanent"),
    ),
    # ------------------------------------------------------------------
    # Tap effects
    # ------------------------------------------------------------------
    _Rule(
        re.compile(r"\btap target (?:\w+ )*(?:creature|permanent|artifact)\b", _I),
        ("tap target creature", "tap opponent creature"),
    ),
    _Rule(
        re.compile(r"\btap all creatures\b", _I),
        ("tap all creatures", "mass tap"),
    ),
    # ------------------------------------------------------------------
    # Fight
    # ------------------------------------------------------------------
    _Rule(
        re.compile(r"\b(?:target |this card )?creature (?:you control )?fights?\b", _I),
        ("fight effect", "creature fights another"),
    ),
    # ------------------------------------------------------------------
    # Landfall
    # ------------------------------------------------------------------
    _Rule(
        re.compile(r"\bwhenever a land enters the battlefield under your control\b", _I),
        ("landfall trigger", "land enters trigger"),
    ),
    # ------------------------------------------------------------------
    # Anthem — buff all your creatures
    # ------------------------------------------------------------------
    _Rule(
        re.compile(r"\bcreatures you control get\b", _I),
        ("anthem effect", "buff your creatures", "pump all creatures"),
    ),
    # ------------------------------------------------------------------
    # Proliferate
    # ------------------------------------------------------------------
    _Rule(
        re.compile(r"\bproliferate\b", _I),
        ("proliferate", "add counters proliferate"),
    ),
    # ------------------------------------------------------------------
    # Scry
    # ------------------------------------------------------------------
    _Rule(
        re.compile(r"\bscry\b", _I),
        ("scry", "look at top of library"),
    ),
    # ------------------------------------------------------------------
    # Keywords — evasion
    # ------------------------------------------------------------------
    _Rule(
        re.compile(r"\bflying\b", _I),
        ("flying", "flying creature", "evasion"),
    ),
    _Rule(
        re.compile(r"\breach\b", _I),
        ("reach", "block flying creatures"),
    ),
    _Rule(
        re.compile(r"\bmenace\b", _I),
        ("menace", "must be blocked by two or more"),
    ),
    _Rule(
        re.compile(r"\btrample\b", _I),
        ("trample", "deal excess damage through blockers"),
    ),
    # ------------------------------------------------------------------
    # Keywords — combat
    # ------------------------------------------------------------------
    _Rule(
        re.compile(r"\bhaste\b", _I),
        ("haste", "attack immediately"),
    ),
    _Rule(
        re.compile(r"\bvigilance\b", _I),
        ("vigilance", "attack without tapping"),
    ),
    _Rule(
        re.compile(r"\bdouble strike\b", _I),
        ("double strike", "deal combat damage twice"),
    ),
    _Rule(
        re.compile(r"\bfirst strike\b", _I),
        ("first strike", "deal damage before other creatures"),
    ),
    # ------------------------------------------------------------------
    # Keywords — damage related
    # ------------------------------------------------------------------
    _Rule(
        re.compile(r"\blifelink\b", _I),
        ("lifelink", "gain life on attack"),
    ),
    _Rule(
        re.compile(r"\bdeathtouch\b", _I),
        ("deathtouch", "kills any creature it damages"),
    ),
    # ------------------------------------------------------------------
    # Keywords — protection
    # ------------------------------------------------------------------
    _Rule(
        re.compile(r"\bindestructible\b", _I),
        ("indestructible", "cannot be destroyed"),
    ),
    _Rule(
        re.compile(r"\bhexproof\b", _I),
        ("hexproof", "cannot be targeted by opponent"),
    ),
    _Rule(
        re.compile(r"\bshroud\b", _I),
        ("shroud", "cannot be targeted"),
    ),
    _Rule(
        re.compile(r"\bprotection from\b", _I),
        ("protection ability",),
    ),
    # ------------------------------------------------------------------
    # Keywords — graveyard / recursion
    # ------------------------------------------------------------------
    _Rule(
        re.compile(r"\bflashback\b", _I),
        ("flashback", "cast from graveyard"),
    ),
    _Rule(
        re.compile(r"\bundying\b", _I),
        ("undying", "return from graveyard"),
    ),
    _Rule(
        re.compile(r"\bpersist\b", _I),
        ("persist", "return with minus counter"),
    ),
    # ------------------------------------------------------------------
    # Keywords — cycling / looting
    # ------------------------------------------------------------------
    _Rule(
        re.compile(r"\bcycling\b", _I),
        ("cycling", "discard to draw"),
    ),
    _Rule(
        re.compile(r"\bdiscard (?:a|one) card.*draw (?:a|one) card\b", _I),
        ("loot effect", "discard then draw"),
    ),
    # ------------------------------------------------------------------
    # Keywords — morph / manifest
    # ------------------------------------------------------------------
    _Rule(
        re.compile(r"\bmorph\b", _I),
        ("morph", "face down creature"),
    ),
    # ------------------------------------------------------------------
    # Keywords — other
    # ------------------------------------------------------------------
    _Rule(
        re.compile(r"\bflash\b", _I),
        ("flash", "play at instant speed"),
    ),
    _Rule(
        re.compile(r"\bcascade\b", _I),
        ("cascade", "cascade spell"),
    ),
    _Rule(
        re.compile(r"\binvestigate\b", _I),
        ("investigate", "create clue token"),
    ),
    _Rule(
        re.compile(r"\bprowess\b", _I),
        ("prowess", "gets bigger when you cast spells"),
    ),
    _Rule(
        re.compile(r"\bconvoke\b", _I),
        ("convoke", "tap creatures to pay mana"),
    ),
    _Rule(
        re.compile(r"\bdelve\b", _I),
        ("delve", "exile cards from graveyard to pay mana"),
    ),
    _Rule(
        re.compile(r"\bkicker\b", _I),
        ("kicker", "pay extra for bonus effect"),
    ),
    _Rule(
        re.compile(r"\boverload\b", _I),
        ("overload", "affect all valid targets"),
    ),
    _Rule(
        re.compile(r"\btribute\b", _I),
        ("tribute", "opponent chooses effect"),
    ),
    _Rule(
        re.compile(r"\bentwine\b", _I),
        ("entwine", "choose all modes"),
    ),
    _Rule(
        re.compile(r"\bsuspend\b", _I),
        ("suspend", "delayed cast with time counters"),
    ),
    _Rule(
        re.compile(r"\bchampion\b", _I),
        ("champion", "exile own creature as cost"),
    ),
    _Rule(
        re.compile(r"\bevolve\b", _I),
        ("evolve", "grow when bigger creature enters"),
    ),
    _Rule(
        re.compile(r"\binspire\b", _I),
        ("inspire", "trigger when untapped"),
    ),
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_template_queries(normalized_text: str) -> list[str]:
    """Return up to MAX_QUERIES_PER_FACE short query strings for a normalized oracle text.

    Rules are evaluated in order.  The first MAX_QUERIES_PER_FACE distinct query
    strings collected across all matching rules are returned.  If no rule fires,
    an empty list is returned — the caller should fall back to oracle-oracle pairs.
    """
    seen: set[str] = set()
    results: list[str] = []
    for rule in _RULES:
        if len(results) >= MAX_QUERIES_PER_FACE:
            break
        if rule.pattern.search(normalized_text):
            for q in rule.queries:
                if q not in seen:
                    seen.add(q)
                    results.append(q)
                    if len(results) >= MAX_QUERIES_PER_FACE:
                        return results
    return results
