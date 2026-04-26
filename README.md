# Spatiality — fast inference for 3D meshes

## Project context
Solo 24h hackathon build (Unicorn Mafia AI, London). Bounty target: Mubit ($8k credits). Spatiality turns any short video pass — phone, GoPro, smart glasses — into a measurable, labelled 3D mesh in under five minutes. The final demo is a mobile-viewable web page where a user opens a 3D reconstruction of a room, sees labeled objects overlaid on the splat, and queries the scene through a chat agent. Ray-Ban Gen 2 is one capture path among many; the headline is **fast inference, queryable 3D**.

Build for modularity. The system is a set of loosely-coupled modules communicating via the filesystem. Any module must be swappable without touching the others. Favor "swappable later" over "correct now".

## Repo layout
```