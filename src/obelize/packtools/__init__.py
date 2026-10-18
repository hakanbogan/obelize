"""What a person writing a pack uses: `pack new` makes one and `pack test` holds it to its fixtures.

Apart from `packs`, which only the scanner's projection and the loader read: running a pack over
its fixtures needs the codemod driver, which reads the schema in `packs`.
"""
