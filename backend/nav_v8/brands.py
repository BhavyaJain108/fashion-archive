"""
Dictionary of small to medium sized fashion brands for testing navigation discovery.
Usage: from backend.nav_v6.brands import BRANDS; url = BRANDS["brand_name"]
"""

BRANDS = {
    # Emerging / Independent Designers
    "eckhaus_latta": "https://www.eckhauslatta.com",
    "entire_studios": "https://www.entirestudios.com",
    "kuurth": "https://kuurth.com",
    "telfar": "https://www.tfrshop.com",
    "bode": "https://www.bodemuseum.com",
    "story_mfg": "https://www.storymfg.com",
    "auralee": "https://www.auralee.jp",
    "our_legacy": "https://www.ourlegacy.com",
    "ahluwalia": "https://www.ahluwaliastudio.com",
    "casablanca": "https://casablancaparis.com",
    "wales_bonner": "https://www.walesbonner.net",
    "botter": "https://www.byvbotter.com",
    "nanushka": "https://www.nanushka.com",
    "jacquemus": "https://www.jacquemus.com",
    "ganni": "https://www.ganni.com",
    "stussy": "https://www.stussy.com",
    "marine_serre": "https://www.marineserre.com",
    "erl": "https://www.erlstudios.com",
    "y_project": "https://www.yproject.fr",

    # Contemporary / Mid-tier
    "cos": "https://www.cos.com/en-us/women",
    "arket": "https://www.arket.com",
    "apc": "https://www.apc.fr",
    "ami": "https://www.amiparis.com",
    "sandro": "https://www.sandro-paris.com",
    "maje": "https://www.maje.com",
    "theory": "https://www.theory.com",
    "vince": "https://www.vince.com",
    "frame": "https://frame-store.com",
    "agolde": "https://www.agolde.com",
    "citizens_of_humanity": "https://www.citizensofhumanity.com",
    "reformation": "https://www.thereformation.com",
    "rouje": "https://www.rouje.com",
    "sezane": "https://www.sezane.com",
    "toteme": "https://www.toteme-studio.com",
    "by_far": "https://www.byfar.com",
    "rixo": "https://www.rixo.co.uk",
    "grlfrnd": "https://www.grlfrnd.com",
    "anine_bing": "https://www.aninebing.com",
    "khaite": "https://www.khaite.com",

    # Streetwear / Youth Culture
    "palace": "https://shop-usa.palaceskateboards.com/",
    "brain_dead": "https://wearebraindead.com",
    "online_ceramics": "https://online-ceramics.com",
    "noon_goons": "https://www.noongoons.com",
    "awake_ny": "https://www.awakeny.com",
    "bianca_chandon": "https://biancachandon.com",
    "pleasures": "https://www.pleasuresnow.com",
    "iggy_nyc": "https://iggy.nyc",
    "cactus_plant_flea_market": "https://cfrmarket.com",
    "real_bad_man": "https://realbadman.net",

    # Japanese / Asian Brands
    "needles": "https://www.needles.jp",
    "kapital": "https://www.kapital.jp",
    "visvim": "https://www.visvim.tv",
    "undercover": "https://undercoverism.com",
    "sacai": "https://www.sacai.jp",
    "hyein_seo": "https://www.hyeinseo.com",
    "ambush": "https://www.ambushdesign.com",
    "human_made": "https://humanmade.jp",
    "wacko_maria": "https://wackomaria.co.jp",
    "comoli": "https://www.comoli.jp",

    # Scandinavian
    "wood_wood": "https://www.woodwood.com",
    "norse_projects": "https://www.norseprojects.com",
    "samsoe": "https://www.samsoe.com",
    "holzweiler": "https://www.holzweiler.no",
    "rodebjer": "https://www.rodebjer.com",

    # British / European Independent
    "martine_rose": "https://www.martine-rose.com",
    "nicholas_daley": "https://www.nicholas-daley.com",
    "stefan_cooke": "https://www.stefancooke.com",
    "bianca_saunders": "https://www.biancasaunders.com",
    "deadwood": "https://www.deadwoodstudios.com",
    "stand_studio": "https://www.standstudio.com",
    "gestuz": "https://www.gestuz.com",

    # Footwear Focused
    "salomon_sportstyle": "https://www.salomon.com/en-us/sportstyle",
    "hoka": "https://www.hoka.com",
    "on_running": "https://www.on-running.com",
    "aeyde": "https://www.aeyde.com",
    "maryam_nassir_zadeh": "https://www.mfrv.com",

    # Accessories / Bags
    "medea": "https://www.medeamedea.com",
    "simon_miller": "https://www.simonmillerusa.com",
    "mansur_gavriel": "https://www.mansurgavriel.com",
    "staud": "https://www.stfrancisflyer.com",
    "jw_pei": "https://www.jwpei.com",

    # Sustainable / Ethical Focus
    "pangaia": "https://www.pangaia.com",
    "ecoalf": "https://www.ecoalf.com",
    "veja": "https://www.veja-store.com",
    "paynter": "https://www.paynterjacket.com",
    "asket": "https://www.asket.com",
}


def get_brand_url(name: str) -> str:
    """Get URL for a brand by name (case-insensitive, handles spaces and hyphens)."""
    # Normalize the input name
    normalized = name.lower().replace(" ", "_").replace("-", "_")

    if normalized in BRANDS:
        return BRANDS[normalized]

    # Try partial matching
    for key in BRANDS:
        if normalized in key or key in normalized:
            return BRANDS[key]

    raise KeyError(f"Brand '{name}' not found. Available brands: {list(BRANDS.keys())}")


def list_brands() -> list[str]:
    """List all available brand names."""
    return sorted(BRANDS.keys())
