from __future__ import annotations

CATEGORY_MAP: dict[str, tuple[str | None, str | None]] = {
    "overall": ("overall", "intelligence_index"),
    "coding": ("coding", "coding_index"),
    "math": ("math", "math_index"),
    "creative_writing": ("creative_writing", None),
    "instruction_following": ("instruction_following", None),
    "hard_prompts": ("hard_prompts", None),
    "expert": ("expert", None),
    "multi_turn": ("multi_turn", None),
    "longer_query": ("longer_query", None),
    "industry_software_and_it_services": ("industry_software_and_it_services", None),
    "industry_legal_and_government": ("industry_legal_and_government", None),
    "industry_life_and_physical_and_social_science": (
        "industry_life_and_physical_and_social_science",
        None,
    ),
    "industry_mathematical": ("industry_mathematical", None),
    "industry_writing_and_literature_and_language": (
        "industry_writing_and_literature_and_language",
        None,
    ),
    "hard_prompts_english": ("hard_prompts_english", None),
    "exclude_ties": ("exclude_ties", None),
    "industry_business_and_management_and_financial_operations": (
        "industry_business_and_management_and_financial_operations",
        None,
    ),
    "industry_entertainment_and_sports_and_media": (
        "industry_entertainment_and_sports_and_media",
        None,
    ),
    "industry_medicine_and_healthcare": ("industry_medicine_and_healthcare", None),
    "english": ("english", None),
    "chinese": ("chinese", None),
    "french": ("french", None),
    "german": ("german", None),
    "japanese": ("japanese", None),
    "korean": ("korean", None),
    "russian": ("russian", None),
    "spanish": ("spanish", None),
}

DEFAULT_CATEGORIES: list[str] = [
    "overall",
    "coding",
    "math",
    "creative_writing",
    "instruction_following",
    "hard_prompts",
    "expert",
    "multi_turn",
    "longer_query",
    "industry_software_and_it_services",
    "industry_legal_and_government",
    "industry_life_and_physical_and_social_science",
    "industry_mathematical",
    "industry_writing_and_literature_and_language",
]

ALL_CATEGORIES: list[str] = list(CATEGORY_MAP.keys())

DISPLAY_NAMES: dict[str, str] = {
    "overall": "Overall",
    "coding": "Coding",
    "math": "Math",
    "creative_writing": "Creative Writing",
    "instruction_following": "Instruction Following",
    "hard_prompts": "Hard Prompts",
    "expert": "Expert",
    "multi_turn": "Multi-Turn",
    "longer_query": "Longer Query",
    "industry_software_and_it_services": "Software & IT",
    "industry_legal_and_government": "Legal & Gov",
    "industry_life_and_physical_and_social_science": "Life & Physical Sci",
    "industry_mathematical": "Industry Math",
    "industry_writing_and_literature_and_language": "Writing & Literature",
    "hard_prompts_english": "Hard Prompts (EN)",
    "exclude_ties": "Exclude Ties",
    "industry_business_and_management_and_financial_operations": "Business & Finance",
    "industry_entertainment_and_sports_and_media": "Entertainment & Media",
    "industry_medicine_and_healthcare": "Medicine & Health",
    "english": "English",
    "chinese": "Chinese",
    "french": "French",
    "german": "German",
    "japanese": "Japanese",
    "korean": "Korean",
    "russian": "Russian",
    "spanish": "Spanish",
}


def display_name(category: str) -> str:
    return DISPLAY_NAMES.get(category, category)


AA_INDEX_FIELDS: list[str] = ["intelligence_index", "coding_index", "math_index"]
