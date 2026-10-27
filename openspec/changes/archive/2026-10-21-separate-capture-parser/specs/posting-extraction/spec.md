## REMOVED Requirements

### Requirement: Both page types are supported
**Reason**: This capability describes what one parser reads, and that parser is now a separately installed private package.
**Migration**: The requirement moves unchanged to the private parser package's own specs.

### Requirement: Core fields are extracted
**Reason**: This capability describes what one parser reads, and that parser is now a separately installed private package.
**Migration**: The requirement moves unchanged to the private parser package's own specs.

### Requirement: Description structure is preserved
**Reason**: This capability describes what one parser reads, and that parser is now a separately installed private package.
**Migration**: Sanitizing and plain-text conversion stay in the app for every parser (capture-import, "Descriptions are sanitized at import"). How the private parser finds the description in its pages moves to its package's own specs.

### Requirement: Company is resolved for anonymous employers
**Reason**: This capability describes what one parser reads, and that parser is now a separately installed private package.
**Migration**: The requirement moves unchanged to the private parser package's own specs.

### Requirement: Header attributes are extracted when present
**Reason**: This capability describes what one parser reads, and that parser is now a separately installed private package.
**Migration**: The requirement moves unchanged to the private parser package's own specs.

### Requirement: Posted date is estimated
**Reason**: This capability describes what one parser reads, and that parser is now a separately installed private package.
**Migration**: Parsers now report a posted date and precision themselves (capture-import, "Built-in posting file format" for the public format). The private parser's own date estimation moves to its package's own specs.

### Requirement: Viewer-specific content is excluded from posting fields
**Reason**: This capability describes what one parser reads, and that parser is now a separately installed private package.
**Migration**: The requirement moves unchanged to the private parser package's own specs.
