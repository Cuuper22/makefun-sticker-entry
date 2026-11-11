# make.fun sticker: the #1 agent

An entry for the make.fun sticker bounty (`makefun-sticker-01`). A robot agent
wearing a gold crown marked **1** gives a cheeky wink above a big white
**make.fun** on a navy nameplate. The sticker is one compact emblem shape inside a
thick white die-cut with a single heavy keyline. Every outline has the same weight,
and there is no fine detail, so it reads at 7 cm and on light or dark laptop lids.

The image is drawn from scratch by `main.py` (Python 3.13, standard library only):

- every shape and every letter is a signed distance field; coverage comes straight
  from the distance, so edges are anti-aliased without supersampling;
- the outlines, the white die-cut margin and the keyline are the same exact fields
  read at wider thresholds, so they are even offsets of the art;
- the wordmark uses a small built-in geometric font made of strokes and arcs,
  scaled automatically to fill the nameplate;
- the result is written as a 1024×1024 RGBA PNG with `zlib` and `struct`.

There is no randomness and no timestamp, so every run writes identical bytes.

## Run

```sh
mkdir -p out
MAKEFUN_OUTPUT_DIR=out python main.py   # writes out/entry.png
```

Without `MAKEFUN_OUTPUT_DIR` it writes `/output/entry.png`, as the contest
sandbox expects. A run takes a few seconds.

## License

MIT, see `LICENSE`.
