import re
import zlib

import numpy as np
import pytest

from app.search import Index
from app.text import build_face_abilities


class BagOfWords:
    """Deterministic stand-in for the ONNX encoder: shared words mean shared direction."""

    def encode(self, texts):
        out = np.zeros((len(texts), 512), dtype=np.float32)
        for row, text in enumerate(texts):
            for token in re.findall(r"[a-z]+", text.lower()):
                out[row, zlib.crc32(token.encode()) % 512] += 1.0
        return out / np.maximum(np.linalg.norm(out, axis=1, keepdims=True), 1e-12)


def face(name, oracle_text, type_line, colors, face_ix=0, oracle_id=None):
    abilities = build_face_abilities(oracle_text=oracle_text, card_name=name, type_line=type_line)
    return {
        "oracle_id": oracle_id, "face_ix": face_ix, "name": name, "mana_cost": None, "type_line": type_line,
        "oracle_text": oracle_text, "power": None, "toughness": None, "loyalty": None, "defense": None,
        "colors": colors, "color_indicator": None, "image_uris": None, "artist": None, "flavor_text": None,
        "cmc": None,
        "abilities": [{"ability_ix": a.ability_ix, "text": a.text, "is_keyword": a.is_keyword} for a in abilities if a.text],
        "_type_categories": [t for t in ("creature", "instant", "sorcery", "enchantment", "artifact", "planeswalker",
                                         "land") if t in type_line.lower()],
        "_hashes": [a.text_hash for a in abilities],
        "_normalized": [a.normalized_text for a in abilities],
    }


def card(oracle_id, name, oracle_text, type_line, colors, *, cmc=1.0, rarity="common", rank=None, layout="normal",
         legalities=None, back=None):
    faces = [face(name, oracle_text, type_line, colors, oracle_id=oracle_id)]
    if back:
        faces.append(face(*back, face_ix=1, oracle_id=oracle_id))
    return {
        "oracle_id": oracle_id, "scryfall_id": f"s{oracle_id}", "name": name if not back else f"{name} // {back[0]}",
        "layout": layout, "cmc": cmc, "edhrec_rank": rank, "rarity": rarity,
        "legalities": legalities or {"modern": "legal"}, "set_code": "tst", "border_color": "black", "faces": faces,
        "_color_identity": "".join(colors), "_keywords": [],
    }


CARDS = [
    card("drake", "Sky Drake", "Flying", "Creature — Drake", ["U"], cmc=3, rank=50),
    card("bird", "Night Bird", "Flying\nWhen this creature enters, draw a card.", "Creature — Bird", ["U"], cmc=3,
         rarity="uncommon", rank=10),
    card("seer", "Grave Seer", "Whenever another creature dies, draw a card.", "Enchantment", ["B"], cmc=2,
         rarity="rare"),
    card("elf", "Llanowar Dork", "{T}: Add {G}.", "Creature — Elf Druid", ["G"], rank=1),
    card("forest", "Green Land", "{T}: Add {G}.", "Land", [], cmc=0),
    card("bolt", "Bolt", "Bolt deals 3 damage to any target.", "Instant", ["R"],
         legalities={"modern": "legal", "vintage": "restricted"}),
    card("bear", "Plain Bear", None, "Creature — Bear", ["G"], cmc=2),
    card("dfc", "Wing Squire", "Flying", "Creature — Human", ["W"], layout="transform",
         back=("Trample Knight", "Trample", "Creature — Knight", ["W"])),
]


@pytest.fixture
def index():
    texts = {h: t for c in CARDS for f in c["faces"] for h, t in zip(f["_hashes"], f["_normalized"])}
    hashes = sorted(texts)
    return Index(CARDS, hashes, BagOfWords().encode([texts[h] for h in hashes]), BagOfWords(), "fake", "2026-08-18")
