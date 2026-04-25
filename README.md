# Build spec — Ray-Ban → 3DGRUT → annotated 3D twin

## Project context
Solo 24h hackathon build (Unicorn Mafia AI, London). Bounty target: Mubit ($8k credits). The final demo is a mobile-viewable web page where a user opens a 3D reconstruction of a room captured from Meta Ray-Ban Gen 2 glasses, sees labeled objects overlaid on the splat, and queries the scene through a chat agent.

Build for modularity. The system is a set of loosely-coupled modules communicating via the filesystem. Any module must be swappable without touching the others. Favor "swappable later" over "correct now".

## Repo layout
```