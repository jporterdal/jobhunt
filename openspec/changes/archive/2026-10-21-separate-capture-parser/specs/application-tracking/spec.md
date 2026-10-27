## MODIFIED Requirements

### Requirement: Applications without an imported posting
The user SHALL be able to create an application by hand, with a required job title and company and an optional URL. The user SHALL be able to link such an application to a posting later, as long as that posting has no application yet. Linking SHALL keep the application's events, documents and contacts.

#### Scenario: Manual application
- **WHEN** the user creates an application for "Data Engineer" at "Acme" with URL `https://acme.example/careers/42`
- **THEN** the application appears on the board, its URL is shown as a link, and it has no posting

#### Scenario: Linking later
- **WHEN** that job is later imported and the user links the application to the new posting
- **THEN** the application keeps its history and now also shows the posting and its "Original posting" link
