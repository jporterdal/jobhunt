# Parser changes: prune-discardable-companions

**Impact: optional.** Parsers that don't change keep working. A parser that adopts the new method lets the app delete asset folders it doesn't need.

This brief is for whoever maintains a jobhunt parser that lives outside the jobhunt repository, whether a person or an agent working in that parser's repository. It's meant to be enough on its own: the contract change is stated here, so you don't need the jobhunt source open.

## Background

- jobhunt imports job postings from files a person drops into an inbox folder. Installed parsers read those files.
- A parser is any object registered under the `jobhunt.parsers` entry-point group. It has these attributes:
  - `name: str`
  - `version: str`
  - `parse(file) -> ParsedPosting | Rejected | None`
  - optionally, `companions(path) -> list[Path]`
- `companions` names the files that belong to `path` and must move with it. An example is the `<name>_files/` folder a browser writes beside a page saved with "Save Page, Complete".
- After the import, a file and its companions move to `inbox/processed/` or `inbox/rejected/`. Nothing is deleted.
- To list the parsers installed in a jobhunt venv:

  ```bash
  python -c "from importlib.metadata import entry_points as e; print([(p.name, p.value) for p in e(group='jobhunt.parsers')])"
  ```

## The contract change

The change adds a second optional method to the parser contract:

```python
def discardable(self, path: Path) -> list[Path]:
    """Which of `path`'s companions may be deleted once `path` has been filed away."""
```

- jobhunt calls it on files directly inside `inbox/processed/` and `inbox/rejected/`, during a *prune*. The server prunes daily, and `jobhunt inbox prune` prunes on demand. Every installed parser is asked about every such file, including files it didn't accept.
- Only paths that your `companions(path)` also returns count. Anything else you return is ignored.
- The file itself and its download metadata (`<name>:Zone.Identifier`) are never deleted, even if returned.
- Returning `[]`, not defining the method, or raising an error all mean "keep everything".
- Return a companion only if the parser never needs it again. Parsers must not read companions anyway: `parse` gets only the file's own bytes.
- The import is unchanged: discardable companions still move with their file. Only the prune deletes them, and a deleted companion can't be restored.

## What to do in a parser repository

1. If the parser defines `companions`, decide which of those companions are disposable. Add `discardable(path)` returning exactly those, built the same way `companions` builds them, so a name-clash rename (`page (2).html` with `page (2)_files`) still matches. If the parser has no disposable companions, change nothing.
2. Consider returning `[]` from both methods for files the parser could never accept (for example, by file extension). The prune asks every parser about every filed-away file, including other parsers' files and other formats.
3. Add tests:
   - `discardable(Path("inbox/A.html"))` returns the expected companion;
   - its result is a subset of `companions` for the same path;
   - it never includes the path itself or `A.html:Zone.Identifier`.
4. **Don't** bump `version`: it marks changes in parsed output, and parsing doesn't change.
5. **Don't** change the entry point. An editable install picks up the new method without reinstalling. Only a changed entry point needs `pip install -e .` again.

## Checking against jobhunt

These checks only work once jobhunt has the change.

- `jobhunt inbox prune --dry-run` lists what would be removed, and removes and records nothing. Expect your disposable companions and nothing else.
- Leave a real prune (`jobhunt inbox prune`, or starting `jobhunt serve`) to the inbox's owner: deleted companions can't be restored.

## Compatibility

```
 parser \ jobhunt   | before this change     | with this change
 -------------------+------------------------+-------------------------------------
 without discardable| as before              | prune runs, removes nothing for it
 with discardable   | method never called    | prune removes the marked companions
```

The method is safe to add before or after jobhunt is updated.
