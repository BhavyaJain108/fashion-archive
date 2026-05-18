# legacy/

Earlier-generation product-page extraction code, superseded by
`prod_page_v2/e0005/`.

Nothing here is imported by the current pipeline. Kept on disk for
reference until we're confident the e0005 replacements cover all
historical behavior.

## What lived here and where it went

| legacy file/dir                 | replaced by                                          |
|---------------------------------|------------------------------------------------------|
| `extractor.py`                  | `e0005/orchestrator.py`                              |
| `strategies/` (7 files)         | `e0005/methods/` (12 method kinds)                   |
| `page_loader.py`                | `e0005/memo.py` (`PageMemo`)                         |
| `api_detector.py`               | `memo._network` capture + `methods/network_api.py`   |
| `llm_image_extractor.py` etc.   | `methods/ld_images.py` + `methods/network_images.py` |
| `models.py`                     | `e0005/schema.py`                                    |
| `cli.py`, `diagnose_brand.py`   | (no replacement yet — to be rebuilt over e0005)      |
| `explore_page.py`               | (debug utility, obsolete)                            |
| `test_*.py`, `debug.ipynb`      | obsolete tests / scratch                             |

Safe to delete this folder once e0005 has been validated on more brands.
