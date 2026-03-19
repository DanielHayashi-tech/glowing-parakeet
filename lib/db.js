import fs from "node:fs";
import path from "node:path";
import { DatabaseSync } from "node:sqlite";

const rootDir = process.cwd();
const dbPath = path.join(rootDir, "data_hub.db");
const sqlPath = path.join(rootDir, "analytics", "starter_queries.sql");

let database;
let initialized = false;

function getDatabase() {
  if (!fs.existsSync(dbPath)) {
    throw new Error(`Database not found at ${dbPath}`);
  }

  if (!database) {
    database = new DatabaseSync(dbPath);
    database.exec("PRAGMA foreign_keys = ON;");
  }

  if (!initialized) {
    if (!fs.existsSync(sqlPath)) {
      throw new Error(`Analytics SQL not found at ${sqlPath}`);
    }
    database.exec(fs.readFileSync(sqlPath, "utf8"));
    initialized = true;
  }

  return database;
}

export function queryAll(sql, params = []) {
  const statement = getDatabase().prepare(sql);
  return statement.all(...params);
}

export function queryOne(sql, params = []) {
  const statement = getDatabase().prepare(sql);
  return statement.get(...params);
}
