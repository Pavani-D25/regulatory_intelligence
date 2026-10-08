import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, familyPath } from "../api";
import { Badge, Card, Empty, ErrorBox, Loading, Table, Td, fmtDate } from "../components/ui";
import useLoad from "../useLoad";

export default function Versions() {
  const [params, setParams] = useSearchParams();
  const q = params.get("q") || "";
  const [text, setText] = useState(q);
  const { data, error, loading } = useLoad(() => api.families(q), [q]);

  return (
    <div className="flex flex-col gap-5">
      <div>
        <h1 className="text-xl font-semibold">Versions</h1>
        <p className="text-sm text-zinc-500">
          Families of versions: an AIS standard with its revisions, amendments and corrigenda, the S.O. 1365(E) master-table
          notifications, CMVR-TAP. Pick one to see its timeline.
        </p>
      </div>
      <form onSubmit={(e) => { e.preventDefault(); setParams(text ? { q: text } : {}); }} className="flex gap-2">
        <input value={text} onChange={(e) => setText(e.target.value)} placeholder="AIS-038, SO-1365, TAP…" className="w-72" />
        <button className="rounded-md bg-brand px-3 py-1.5 text-sm text-white">Find</button>
      </form>
      <ErrorBox error={error} />
      {loading ? <Loading /> : data && (
        <Card title={`${data.count} families${q ? ` matching “${q}”` : ""}`}>
          {data.families.length === 0 ? <Empty>No family matches.</Empty> : (
            <Table head={["Family", "Current version", "Title", "Versions", "Latest"]}>
              {data.families.map((f) => (
                <tr key={f.family_key} className="hover:bg-zinc-50">
                  <Td><Link to={familyPath(f.family_key)} className="font-mono text-[13px]">{f.family_key}</Link>
                    {f.in_scope && <span className="ml-2"><Badge tone="blue">in scope</Badge></span>}</Td>
                  <Td className="font-mono text-[13px]">{f.current || "—"}</Td>
                  <Td className="max-w-sm"><div className="line-clamp-2 text-zinc-600">{f.title || "—"}</div></Td>
                  <Td>{f.versions}</Td>
                  <Td className="whitespace-nowrap">{fmtDate(f.latest)}</Td>
                </tr>
              ))}
            </Table>
          )}
        </Card>
      )}
    </div>
  );
}
