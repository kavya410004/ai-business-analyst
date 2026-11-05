# AI Business Analyst (In Progress)

An AI-powered business analyst designed to analyse business data, answer business-related questions, and generate actionable insights using AI agents.

## Approach

The project begins with analysing the provided CRM datasets to understand the business entities, relationships, and data quality. Based on these findings, a relational database schema is designed to organise the data before implementing the AI agent and its tools.

## Key Design Decisions

The following assumptions and decisions were made during data analysis and database design:

1. **Owner identification:** Since owner names are the only available identifiers, records with the same owner name are assumed to represent the same person.

2. **Historical snapshots:** Segment and region appear in both Leads and Deals. These attributes are retained in Deals as historical snapshots, allowing the original values to be preserved even if a lead's segment or region changes later. This is an intentional denormalization.

3. **Deal ownership:** Each deal is assumed to have a single owner.

## Known Limitations

- Owner names may not uniquely identify individuals. Different people could share the same name.
- The source data does not provide enough information to independently verify owner identities.
- The historical accuracy of segment and region depends on the values captured in the source data.
- Some records contain missing or inconsistent information, which may affect analysis.

## Project Structure

- `docs/` – Technical documentation and database design.
- `docs/images/` – Entity Relationship Diagram.

## Current Status

Initial CRM data analysis and database design completed. Database implementation and AI agent development are pending.