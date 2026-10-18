# License and third-party notices

ScholarNoteLM is licensed under the GNU General Public License, version 3 or
(at your option) any later version (SPDX: GPL-3.0-or-later). See LICENSE.
Third-party components retain their original copyright and license terms.

- Marker 1.6.0: adapted source at services/marker/vendor, GPL-3.0-or-later.
  Original license: services/marker/vendor/LICENSE; upstream:
  https://github.com/datalab-to/marker . ScholarNoteLM's local-loading adapter
  and other changes are distributed in the source repository.
- Jina Embeddings v4 tokenizer: services/downloader/resources/jina-embeddings-v4,
  with the original LICENSE and tokenizer resources retained.
- Go Noto font: SIL Open Font License 1.1. Copyright notices and full license:
  scripts/install/FONT_NOTICE.txt and scripts/install/FONT_LICENSE.txt.
- Local model weights: separately supplied, with original model cards and
  terms retained under models/marker. See scripts/install/ASSET_NOTICES.md.
  The application's GPL license does not relicense these weights.
- Rust and JavaScript dependencies: exact versions in Cargo.lock and the npm
  lockfiles. Their individual licenses apply. The precompiled app includes
  available license/notice files from the build dependencies under its
  Contents/Resources/third-party directory.
- Python dependencies and Chromium are downloaded by the installer rather
  than bundled into the precompiled app; retain their installed license files.

When distributing the precompiled program, provide the matching complete
ScholarNoteLM source and build/installation scripts from the same release.
