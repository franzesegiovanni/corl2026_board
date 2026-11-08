---
description: Publish your own copy of the CoRL 2026 Board as a private Claude artifact
---

Publish my own copy of the CoRL 2026 Board.

Link of my existing copy, if I gave one: $ARGUMENTS

1. The page is `board/corl2026_board.html`. Do not change the file. If I gave a link above, update that artifact in place (pass it as `url`, reading it first if needed) so the link and my saved data stay the same. Otherwise publish it as a NEW artifact owned by me, and never pass the `url` of someone else's artifact.
2. Publish `board/abstracts.json` alongside the page as the supporting file `abstracts.json` (Artifact `files`: `{"abstracts.json": "board/abstracts.json"}`); the page loads the paper abstracts from it.
3. Declare these capabilities, so my likes, notes, liked people, Thursday plan and poster photos are saved privately to my account:
   `{"db": {}, "user": {}, "assets": {}}`
4. Use the icon `calendar` and this description: "All CoRL 2026 papers by day, session, topic and people, workshops and a personal Thursday plan, with private likes, notes and poster photos."

When it is published, give me the link and tell me briefly:
- My likes, flags, notes, liked people, workshop plan and photos are private to me and sync across my devices.
- The artifact is private until I share it from its Share menu.
- To get updates later: `git pull`, then run `/publish-board <my existing link>` so the same artifact is updated.
