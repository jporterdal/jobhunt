## ADDED Requirements

### Requirement: Insights page
The navigation SHALL include an Insights section. It SHALL show the posting recommendations and the skill recommendations (see the `recommendations` capability). When there is nothing to recommend, because no posting has skills or the profile has no skills, the page SHALL say which of the two is missing and how to fix it.

#### Scenario: Recommendations shown
- **WHEN** postings have skills and the profile has skills, and the user opens Insights
- **THEN** the page shows the recommended postings and the recommended skills

#### Scenario: Empty profile
- **WHEN** postings have skills but no skill has a level, and the user opens Insights
- **THEN** the page says the profile has no skills yet and links to the profile page

## REMOVED Requirements

### Requirement: Insights placeholder
**Reason**: The Insights section now shows recommendations, so it is no longer a placeholder.
**Migration**: None. The section stays in the navigation at the same address; see "Insights page".
