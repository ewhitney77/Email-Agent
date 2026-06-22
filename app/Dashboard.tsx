"use client";

import { useMemo, useState } from "react";
import type { Company, Role, Snapshot } from "./types";

function scoreClass(score: number, threshold: number): string {
  if (score >= threshold) return "s-good";
  if (score >= threshold - 0.15) return "s-mid";
  return "s-low";
}

function formatWhen(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function Dashboard({ data }: { data: Snapshot }) {
  const [onlyMatches, setOnlyMatches] = useState(false);
  const [sortBy, setSortBy] = useState<"score" | "name">("score");

  const companies = useMemo(() => {
    const list: Company[] = data.companies.map((c) => ({
      ...c,
      roles: onlyMatches ? c.roles.filter((r) => r.matched) : c.roles,
    }));
    if (sortBy === "name") {
      list.sort((a, b) => a.company.localeCompare(b.company));
    } else {
      list.sort((a, b) => b.top_score - a.top_score);
    }
    return list;
  }, [data.companies, onlyMatches, sortBy]);

  return (
    <main className="wrap">
      <header className="page">
        <h1>Job Match Dashboard</h1>
        <div className="sub">
          Open roles at your target companies, stack-ranked by semantic match to
          your ideal-role profile.
        </div>
      </header>

      {data.sample && (
        <div className="banner">
          Showing seed sample data. The scheduled GitHub Action will replace this
          with live scraped results on its next run.
        </div>
      )}

      <div className="stats">
        <div className="stat">
          <div className="num">{data.company_count}</div>
          <div className="lbl">companies watched</div>
        </div>
        <div className="stat">
          <div className="num">{data.total_matches}</div>
          <div className="lbl">roles above threshold</div>
        </div>
        <div className="stat">
          <div className="num">{data.threshold.toFixed(2)}</div>
          <div className="lbl">match threshold</div>
        </div>
      </div>

      <div className="controls">
        <label>
          <input
            type="checkbox"
            checked={onlyMatches}
            onChange={(e) => setOnlyMatches(e.target.checked)}
          />
          Only show matches
        </label>
        <label>
          Sort companies by
          <select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value as "score" | "name")}
          >
            <option value="score">Top match score</option>
            <option value="name">Company name</option>
          </select>
        </label>
      </div>

      {companies.map((c) => (
        <section className="company" key={c.company}>
          <div className="company-head">
            <div>
              <h2>{c.company}</h2>
              <div className="meta">
                {c.match_count > 0 ? (
                  <span className="badge match">{c.match_count} match</span>
                ) : (
                  <span>no matches</span>
                )}{" "}
                · {c.roles.length} role{c.roles.length === 1 ? "" : "s"} shown
                {c.error ? (
                  <span className="err"> · scrape error</span>
                ) : null}
              </div>
            </div>
            {c.url ? (
              <a
                className="careers"
                href={c.url}
                target="_blank"
                rel="noopener noreferrer"
              >
                careers page ↗
              </a>
            ) : null}
          </div>

          {c.roles.length === 0 ? (
            <div className="empty">
              {c.error
                ? `Could not scrape this page (${c.error}). It may need a link_selector or "render": "js" in targets.json.`
                : onlyMatches
                ? "No roles above the threshold."
                : "No postings found."}
            </div>
          ) : (
            <ul className="roles">
              {c.roles.map((r: Role, i: number) => (
                <li
                  className={`role ${r.matched ? "is-match" : ""}`}
                  key={`${r.url}-${i}`}
                >
                  <div className={`score ${scoreClass(r.score, data.threshold)}`}>
                    {r.score.toFixed(2)}
                  </div>
                  <div className="role-body">
                    <a
                      className="role-title"
                      href={r.url}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      {r.title}
                      {r.matched ? <span className="badge match">match</span> : null}
                    </a>
                    <div className="role-sub">
                      closest profile: {r.best_role || "—"}
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      ))}

      <footer className="page">
        Last updated {formatWhen(data.generated_at)} · {data.embedding_backend} ·
        profiles: {data.ideal_roles.join(", ")}
      </footer>
    </main>
  );
}
