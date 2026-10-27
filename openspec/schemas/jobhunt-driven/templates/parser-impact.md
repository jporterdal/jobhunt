# Parser impact: <!-- change name -->

**Impact: <!-- none | optional | required -->.** <!-- One or two sentences: why, and what a parser that does nothing will see. -->

<!-- For impact "none", delete everything below this line. -->

This brief is for whoever maintains a jobhunt parser that lives outside the jobhunt repository, whether a person or an agent working in that parser's repository. The contract change is stated here, so you don't need the jobhunt source open.

## Background

<!-- What parsers are and how they plug in, as much as this change needs: the `jobhunt.parsers` entry-point group,
     the methods involved, and how to list the installed parsers. -->

## The contract change

<!-- Signatures, semantics, when and on which files jobhunt calls them, and what jobhunt does with the results. -->

## What to do in a parser repository

<!-- Numbered steps, the tests to add, and what not to change (version, entry point, reinstalling). -->

## Checking against jobhunt

<!-- Read-only or dry-run checks first; leave anything destructive to the data's owner. -->

## Compatibility

```
 parser \ jobhunt   | before this change     | with this change
 -------------------+------------------------+------------------------
 unchanged          |                        |
 updated            |                        |
```
