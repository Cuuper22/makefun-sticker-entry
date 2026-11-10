# make.fun sticker: the #1 agent

An entry for the make.fun sticker bounty (`makefun-sticker-01`). A cheerful robot
agent wears a gold crown marked **1**, flanked by winner's sparkles, above a bold
**make.fun** nameplate, all inside one thick white die-cut border with a dark
keyline, so it reads on light and dark laptop lids alike.

The image is drawn from scratch by `main.py` (Python 3.13, standard library only):

- every shape and every letter is a signed distance field; coverage comes straight
  from the distance, so edges are anti-aliased without supersampling;
- the outlines and the die-cut are the same fields read at wider thresholds, and the
  die-cut's parts meet in smooth fillets (a smooth union, re-measured to keep the
  keyline an even width);
- the wordmark uses a small built-in geometric font made of strokes and arcs;
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
