"""Parse independent order attributes without imposing a word order."""
import re
from decimal import Decimal

from .models import Material, Product, ProductAlias


COLORS = {
    "p": "핑크", "pg": "핑크", "pink": "핑크", "핑크": "핑크", "핑크골드": "핑크",
    "rose": "핑크", "로즈": "핑크", "로즈골드": "핑크",
    "g": "옐로우", "y": "옐로우", "yg": "옐로우", "yellow": "옐로우",
    "옐로우": "옐로우", "옐로": "옐로우", "옐로우골드": "옐로우",
    "w": "화이트", "wg": "화이트", "white": "화이트", "화이트": "화이트", "화이트골드": "화이트",
    "b": "베이지", "bg": "베이지", "beige": "베이지", "베이지": "베이지", "베이지골드": "베이지",
}
COLOR_WORDS = "|".join(re.escape(word) for word in sorted(COLORS, key=len, reverse=True))
MATERIAL = re.compile(
    rf"(?<!\S)(?P<material>14\s*(?:k|케이)|18\s*(?:k|케이)|24\s*(?:k|케이)|순금|925\s*(?:silver|실버)|silver\s*925|s925|925|실버)(?P<color>{COLOR_WORDS})?(?!\S)", re.I,
)
COLOR = re.compile(rf"(?<!\S)({COLOR_WORDS})(?!\S)", re.I)
LENGTH = re.compile(r"(?<!\S)(\d+(?:\.\d+)?)\s*(cm|센티미터|센티|m|미터)(?=$|\s|[xX*×]\s*\d|\d+\s*개)", re.I)
QUANTITY = re.compile(r"(?<!\S)(?:[xX*×]\s*(\d+)|(\d+)\s*(?:개|pcs?))(?=$|\s)", re.I)


def resolve_order_product(model_number):
    product = Product.objects.filter(code__iexact=model_number, active=True).first()
    if product:
        return product
    aliases = list(ProductAlias.objects.select_related("product").filter(
        alias__iexact=model_number, product__active=True,
    )[:2])
    return aliases[0].product if len(aliases) == 1 else None


def parse_quick_order_lines(raw_text, default_quantity=1):
    parsed, invalid = [], []
    materials = {m.name.casefold(): m for m in Material.objects.filter(active=True)}
    for line_number, source in enumerate(raw_text.splitlines(), 1):
        if not source.strip():
            continue
        parts = [part.strip() for part in source.split("/")]
        text = parts[0]
        matches = list(MATERIAL.finditer(text))
        if len(matches) != 1:
            invalid.append(line_number)
            continue
        match = matches[0]
        name = re.sub(r"\s+", "", match["material"]).lower()
        name = "24k" if name == "순금" else "925 silver" if name in ("925silver", "925실버", "silver925", "s925", "925", "실버") else name.replace("케이", "k")
        material = materials.get(name)
        colors = [COLORS[match["color"].lower()]] if match["color"] else []
        text = text[:match.start()] + " " + text[match.end():]
        colors += [COLORS[m[1].lower()] for m in COLOR.finditer(text)]
        text = COLOR.sub(" ", text)
        lengths = list(LENGTH.finditer(text))
        if not material or len(set(colors)) > 1 or len(lengths) != 1:
            invalid.append(line_number)
            continue
        length = lengths[0]
        amount = Decimal(length[1])
        finished = length[2].lower() in ("cm", "센티미터", "센티")
        text = text[:length.start()] + " " + text[length.end():]
        quantities = list(QUANTITY.finditer(text))
        quantity = Decimal(quantities[0][1] or quantities[0][2]) if quantities else Decimal(str(default_quantity or 1))
        model = " ".join(QUANTITY.sub(" ", text).split())
        option_detail = " / ".join(p for p in parts[1:] if p) if finished else ""
        # Unrecognised numeric attributes must not silently become part of a model.
        if (amount <= 0 or quantity <= 0 or len(quantities) > 1 or not model
                or re.search(r"(?<!\S)(?:[xX*×+-]\d+(?:\.\d+)?(?:cm|m|개)?|\d+(?:\.\d+)?(?:cm|m|개))(?!\S)", model, re.I)
                or len(model) > 40 or len(length[1] + "CM") > 40 or len(option_detail) > 200
                or (not finished and (amount >= 100000000 or amount.as_tuple().exponent < -2))
                or (finished and (quantity >= 100000000 or quantity != quantity.to_integral_value()))):
            invalid.append(line_number)
            continue
        product = resolve_order_product(model)
        if product and len(product.code) > 40:
            invalid.append(line_number)
            continue
        parsed.append({
            "source_line": source.strip(), "material": material,
            "color": colors[0] if colors else "", "model_number": product.code if product else model,
            "length_spec": f"{length[1]}{'CM' if finished else 'M'}",
            "delivery_type": "finished" if finished else "semi",
            "option_detail": option_detail,
            "quantity": quantity if finished else amount,
        })
    return parsed, invalid
