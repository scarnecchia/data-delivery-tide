# Loading Dock: Data Delivery Tracking and Conversion

## The problem

Data deliveries arrive as SAS files on a network share. The directory structure encodes metadata (project, workplan, version, status), but there is no centralised system that tracks what has arrived, what its status is, or whether it has been converted to a format suitable for downstream analysis. The result is that staff must manually check directories to determine delivery status, conversion is ad hoc, and there is no reliable way to know whether a given dataset is current, superseded, or failed.

This is not a question of volume alone. The challenge is that delivery status is implicit in directory naming conventions that vary across delivery types, and that the relationship between a delivery's arrival and its readiness for use involves multiple state transitions that are currently tracked, if at all, through informal processes.

## What Loading Dock does

Loading Dock is a lightweight pipeline that automates three functions:

**Discovery.** A crawler periodically scans configured directories on the network share. It parses project, workplan, version, and status information from the directory structure according to configurable rules (called *lexicons*), inventories the files present, and registers each delivery in a central database.

**Status tracking.** The registry API maintains a record of every delivery: when it was first seen, its current status, whether it has been converted, and any associated metadata. Status transitions are validated against the lexicon rules, so invalid state changes are rejected at the system level rather than discovered after the fact. When a delivery's status changes, the system emits an event that downstream consumers can act on.

**Conversion.** A converter component reads SAS7BDAT files from registered deliveries and writes them as Parquet files, a modern columnar format that is faster to query and substantially smaller on disk. Conversion can run as a one-shot backfill (processing a backlog) or as a persistent daemon that converts deliveries as they arrive.

## What this means in practice

Once deployed, Loading Dock provides a single source of truth for delivery status. Rather than checking directories manually or relying on informal communication about what has arrived and in what state, staff and downstream systems can query the registry API. The system answers questions such as: which deliveries are pending review? Which have passed review? Which have been converted and are ready for analysis?

The system is configurable rather than hardcoded. Different delivery types may have different status vocabularies, different directory conventions, and different rules for determining when a delivery is actionable. These differences are captured in lexicon configuration files. Adding a new delivery type means writing a new JSON configuration file; the pipeline infrastructure itself does not change.

## Technical characteristics

Loading Dock runs on a single RHEL server with no external database dependencies. It uses SQLite for storage, Python for the application logic, and a lightweight web framework for the API. It requires no Docker containers, no cloud services, and no specialised infrastructure. The system is designed to be operated by a small team and to run unattended via standard process management (cron).

Resource requirements are modest. The system's primary constraint is disk I/O during SAS-to-Parquet conversion, which can be parallelised across multiple processes if throughput becomes an issue.

## Current status

The core pipeline is implemented and functional: the crawler, registry API, event system, and converter are all operational. The system currently ships with lexicons for QA delivery types but can be extended to others by adding a new configuration file.
