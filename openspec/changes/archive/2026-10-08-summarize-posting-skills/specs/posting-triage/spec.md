## ADDED Requirements

### Requirement: Skills asked for panel
The posting detail page SHALL list the posting's skill marks in a "Skills asked for" panel. The panel's heading SHALL show the number of marks and, when the flag is set, that labelling is complete. Under the heading, the panel SHALL show a short description of four sentences saying that:
- it lists the user's marks on this posting (text they selected, or model suggestions they accepted);
- suggestions not yet accepted are in "Model says", below the description, where they can be accepted or rejected;
- importance applies to this posting only;
- level is the user's level for the skill under this name wherever it is marked, setting it adds that skill to the profile and clearing it removes it, and the level of a linked profile skill is changed from the skill summary's link to the profile page.

The heading and description SHALL always be visible. The marks with their controls (importance, level, remove) and the labelling-complete control SHALL be in a section that is collapsed each time the page loads, and that the user can expand and collapse. Changing something in the expanded section SHALL leave it expanded. Marks SHALL be highlighted in the description, and text SHALL be markable by selection, whether the section is expanded or not.

#### Scenario: Collapsed when the page loads
- **WHEN** the user opens a posting with 12 marks and labelling complete
- **THEN** the panel's heading reads "Skills asked for (12 marked · labelling complete)", its description is shown, and the marks and their controls are hidden until the user expands them

#### Scenario: Stays open while editing
- **WHEN** the user expands the section and changes a mark's importance
- **THEN** the change is saved and the section is still expanded

#### Scenario: Marking while collapsed
- **WHEN** the section is collapsed and the user selects "Terraform" in the description and marks it
- **THEN** `Terraform` is highlighted in the description and the heading counts one more mark

#### Scenario: No marks
- **WHEN** a posting has no marks
- **THEN** the heading reads "Skills asked for (none marked)", and the collapsed section says to select text in the description to mark a skill
