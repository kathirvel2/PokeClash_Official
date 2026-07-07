"use strict";

const fs = require("node:fs");
const path = require("node:path");

const showdownDir = path.resolve(
	process.env.SHOWDOWN_DIR || path.resolve(__dirname, "..", "..", "pokeplaybot", "server", "pokemon-showdown")
);
const distEntry = path.join(showdownDir, "dist", "sim", "index.js");

function emit(payload) {
	process.stdout.write(`${JSON.stringify(payload)}\n`);
}

function emitError(message) {
	emit({ok: false, error: message});
}

if (!fs.existsSync(distEntry)) {
	emitError(`Pokemon Showdown is not built yet. Expected ${distEntry}.`);
	process.exit(0);
}

const {Dex, TeamValidator, Teams} = require(distEntry);

function fail(message) {
	throw new Error(message);
}

function parsePayload(raw) {
	try {
		return JSON.parse(String(raw || "{}"));
	} catch (error) {
		fail(`Invalid JSON payload: ${error.message}`);
	}
}

function normalizeStats(raw, fallbackValue) {
	const source = raw && typeof raw === "object" ? raw : {};
	return {
		hp: Number(source.hp ?? fallbackValue),
		atk: Number(source.atk ?? fallbackValue),
		def: Number(source.def ?? fallbackValue),
		spa: Number(source.spa ?? fallbackValue),
		spd: Number(source.spd ?? fallbackValue),
		spe: Number(source.spe ?? fallbackValue),
	};
}

function toID(value) {
	return String(value || "").toLowerCase().replace(/[^a-z0-9]+/g, "");
}

function normalizeMoves(dex, rawMoves) {
	if (!Array.isArray(rawMoves) || !rawMoves.length) {
		fail("Each Pokemon needs at least one move.");
	}
	return rawMoves.map(rawMove => {
		const move = dex.moves.get(String(rawMove || "").trim());
		if (!move.exists) {
			fail(`Unknown move: ${String(rawMove || "")}`);
		}
		return move.name;
	});
}

function normalizeSet(dex, rawSet) {
	const species = dex.species.get(String(rawSet.species || rawSet.name || "").trim());
	if (!species.exists) {
		fail(`Unknown species: ${String(rawSet.species || rawSet.name || "")}`);
	}

	const ability = String(rawSet.ability || "").trim();
	if (ability) {
		const abilityEntry = dex.abilities.get(ability);
		if (!abilityEntry.exists) {
			fail(`Unknown ability: ${ability}`);
		}
	}

	const item = String(rawSet.item || "").trim();
	if (item) {
		const itemEntry = dex.items.get(item);
		if (!itemEntry.exists) {
			fail(`Unknown item: ${item}`);
		}
	}

	const teraType = String(rawSet.teraType || species.types?.[0] || "Normal").trim();
	const level = Math.max(1, Math.min(100, Number(rawSet.level || 100)));

	return {
		name: String(rawSet.nickname || rawSet.name || species.baseSpecies || species.name).trim() || species.name,
		species: species.name,
		item,
		ability,
		moves: normalizeMoves(dex, rawSet.moves),
		nature: String(rawSet.nature || "Serious").trim() || "Serious",
		gender: String(rawSet.gender || "").trim(),
		shiny: Boolean(rawSet.shiny),
		level,
		happiness: Math.max(0, Math.min(255, Number(rawSet.happiness ?? 255))),
		teraType,
		evs: normalizeStats(rawSet.evs, 0),
		ivs: normalizeStats(rawSet.ivs, 31),
	};
}

function validateStartingForm(dex, set) {
	const species = dex.species.get(set.species);
	const forme = String(species.forme || "");
	if (
		species.battleOnly ||
		species.isMega ||
		species.isPrimal ||
		forme === "Ultra" ||
		forme === "Gmax" ||
		species.isNonstandard === "Gigantamax" ||
		forme.endsWith("-Mega")
	) {
		return `${set.name || set.species} must be imported in its base form, not ${species.name}.`;
	}
	return null;
}

function validateTeam(formatid, dex, team) {
	const validator = TeamValidator.get(formatid);
	const problems = validator ? (validator.validateTeam(team) || []) : [];
	for (const set of team) {
		const startingFormProblem = validateStartingForm(dex, set);
		if (startingFormProblem) problems.push(startingFormProblem);
	}
	return problems;
}

function resolveFormat(formatid) {
	const format = Dex.formats.get(formatid);
	if (!format?.exists) {
		fail(`Unknown format: ${formatid}`);
	}
	return format;
}

function packTeam(payload) {
	const formatid = String(payload.formatid || "gen9pokeclashcompetitive").trim();
	const rawTeam = Array.isArray(payload.team) ? payload.team : [];
	if (!rawTeam.length) {
		fail("Cannot pack an empty team.");
	}

	const format = resolveFormat(formatid);
	const dex = Dex.forFormat(format);
	const team = rawTeam.map(rawSet => normalizeSet(dex, rawSet));
	const problems = validateTeam(formatid, dex, team);

	emit({
		ok: true,
		formatid,
		packedTeam: Teams.pack(team),
		exportText: Teams.export(team).trim(),
		problems,
	});
}

function importTeam(payload) {
	const formatid = String(payload.formatid || "gen9pokeclashcompetitive").trim();
	const text = String(payload.text || "").trim();
	if (!text) {
		fail("Missing Showdown team export text.");
	}

	const format = resolveFormat(formatid);
	const dex = Dex.forFormat(format);
	const importedTeam = Teams.import(text);
	if (!Array.isArray(importedTeam) || !importedTeam.length) {
		fail("No Pokemon were found in that Showdown export.");
	}

	const team = importedTeam.map(rawSet => normalizeSet(dex, rawSet));
	const problems = validateTeam(formatid, dex, team);

	emit({
		ok: true,
		formatid,
		exportText: Teams.export(team).trim(),
		problems,
		team,
	});
}

function handlePayload(payload) {
	switch (String(payload.type || "")) {
	case "pack-team":
		packTeam(payload);
		return;
	case "import-team":
		importTeam(payload);
		return;
	}
	fail(`Unsupported team packer command: ${String(payload.type || "")}`);
}

let input = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", chunk => {
	input += chunk;
});
process.stdin.on("end", () => {
	const text = String(input || "").trim();
	if (!text) {
		emitError("Missing team packer payload.");
		process.exit(1);
		return;
	}
	try {
		handlePayload(parsePayload(text));
		process.exit(0);
	} catch (error) {
		emitError(error?.message || String(error));
		process.exit(1);
	}
});
