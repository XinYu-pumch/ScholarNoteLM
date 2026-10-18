# Marker models and font resources

This pack contains only the files listed in `assets.json`: the seven checkpoint
directories loaded by ScholarNoteLM's Marker adapter, and its Go Noto font.
It contains no Python environment, BADR installation, API keys or research papers.
The files are unmodified and SHA-256 checked against the working baseline.

- Marker code: version 1.6.0, maintained upstream at
  https://github.com/datalab-to/marker ; the checked-in vendor code includes its
  GPL-3.0-or-later license. This resource pack does not change that code license.
- Surya 0.13.1 names these dated checkpoints at https://models.datalab.to .
  Original model cards are included in each checkpoint directory. Most cards
  identify CC BY-NC-SA 4.0: https://creativecommons.org/licenses/by-nc-sa/4.0/ .
  The inline-math card does not provide a complete licensing declaration.
  Do not treat the pack as a blanket commercial redistribution grant; confirm
  the applicable upstream model terms before public/commercial distribution.
- Go Noto: https://github.com/satbyy/go-noto-universal . The project distinguishes
  its public-domain build scripts from generated fonts under the SIL Open Font
  License. `FONT_NOTICE.txt` preserves the font's embedded copyright/license
  notices. The font binary is unchanged.

The old Datalab endpoints returned HTTP 403 during installation validation.
For the source-install edition, obtain the matching models directory separately; the installer never
silently substitutes a newer model, changes TLS verification, or downloads models
during PDF conversion. Pack integrity does not establish licensing rights.
