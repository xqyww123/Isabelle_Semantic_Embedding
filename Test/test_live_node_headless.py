"""
Headless end-to-end test of the live-node lookup (Isabelle2026 port: node-match test H and
the design review's T5).

It builds a fixture tree at run time -- a theory under a plain absolute directory, one
reached through a directory symlink, a hard link, a theory under USER_HOME (whose node a
Headless session names in folded form, "~/..."), an alias with another file name and a
directory named "it's" -- generates a theory that imports the fixtures and runs
Test/Live_Node/live_node_checks.ML, and loads it through an Isabelle server session on
the Semantic_Embedding heap.  Every fixture theory is then a live PIDE node.

    python3 Test/test_live_node_headless.py WORK_DIR

WORK_DIR is a parent directory: the run creates a fresh directory in it and another
under USER_HOME, and removes only those two.  It needs `isabelle` (Isabelle2026, with
this component and its built jar) on PATH and the Semantic_Embedding heap built; it
aborts if starting the session would build.  It stops only the server it started.  Exit
0 iff the theory loads with no error and the checks report success.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CHECKS = os.path.join(HERE, "Live_Node", "live_node_checks.ML")


def user_home() -> str:
    return subprocess.run(["isabelle", "getenv", "-b", "USER_HOME"],
                          capture_output=True, text=True, check=True).stdout.strip()


def write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def theory(name: str, const: str) -> str:
    # named symbols before the definition: Headless reads the file with ASCII escapes, so
    # character and symbol offsets differ from here on (a character-counting lookup misses)
    return (f"theory {name}\n  imports Main\nbegin\n\n"
            "text \\<open>\\<alpha> \\<beta> \\<gamma> \\<Rightarrow> \\<forall>\\<close>\n\n"
            f"definition {const} :: nat where \"{const} = 1\"\n\nend\n")


def fixtures(work: str, home_dir: str, home_rel: str):
    """The fixture tree in the fresh directories `work` and `home_dir` (USER_HOME/home_rel);
    returns (targets, bads) for Live_Node_Checks.run."""
    abs_thy = os.path.join(work, "abs", "LN_Abs.thy")
    write(abs_thy, theory("LN_Abs", "ln_abs"))
    os.symlink(os.path.join(work, "abs"), os.path.join(work, "absalias"))
    os.makedirs(os.path.join(work, "hard"))
    os.link(abs_thy, os.path.join(work, "hard", "LN_Abs.thy"))
    write(os.path.join(work, "real", "LN_Link.thy"), theory("LN_Link", "ln_link"))
    os.symlink(os.path.join(work, "real"), os.path.join(work, "link"))
    write(os.path.join(home_dir, "LN_Home.thy"), theory("LN_Home", "ln_home"))
    os.makedirs(os.path.join(work, "other"))
    os.symlink(abs_thy, os.path.join(work, "other", "Other.thy"))
    write(os.path.join(work, "it's", "LN_Abs.thy"), theory("LN_Abs", "ln_abs"))

    targets = [
        ("LN_Abs.ln_abs",
         [abs_thy, os.path.join(work, "absalias", "LN_Abs.thy"),
          os.path.join(work, "hard", "LN_Abs.thy"),
          os.path.join(work, "abs", "..", "abs", "LN_Abs.thy"),
          work + "/abs//LN_Abs.thy"]),
        ("LN_Link.ln_link",
         [os.path.join(work, "link", "LN_Link.thy"), os.path.join(work, "real", "LN_Link.thy")]),
        ("LN_Home.ln_home",
         [f"~/{home_rel}/LN_Home.thy", os.path.join(home_dir, "LN_Home.thy"),
          f"$USER_HOME/{home_rel}/LN_Home.thy"]),
    ]
    bads = [os.path.join(work, "nowhere", "LN_Abs.thy"), os.path.join(work, "other", "Other.thy"),
            os.path.join(work, "it's", "LN_Abs.thy"), "$LN_UNDEFINED/LN_Abs.thy",
            "C:\\x\\LN_Abs.thy"]
    return targets, bads


def ml_string(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def main() -> int:
    parent = os.path.abspath(sys.argv[1])
    os.makedirs(parent, exist_ok=True)
    work = tempfile.mkdtemp(prefix="live_node_h.", dir=parent)
    home_dir = tempfile.mkdtemp(prefix="live_node_h.", dir=user_home())
    home_rel = os.path.basename(home_dir)
    try:
        return run(work, home_dir, home_rel)
    finally:
        shutil.rmtree(work, ignore_errors=True)
        shutil.rmtree(home_dir, ignore_errors=True)


def run(work: str, home_dir: str, home_rel: str) -> int:
    targets, bads = fixtures(work, home_dir, home_rel)
    ml_targets = "[" + ", ".join(
        f"({ml_string(c)}, [{', '.join(ml_string(s) for s in ss)}])" for c, ss in targets) + "]"
    ml_bads = "[" + ", ".join(ml_string(b) for b in bads) + "]"
    write(os.path.join(work, "Live_Node_Test.thy"),
          "theory Live_Node_Test\n"
          "  imports Semantic_Embedding.Semantic_Embedding \"abs/LN_Abs\" \"link/LN_Link\"\n"
          f"    \"~/{home_rel}/LN_Home\"\nbegin\n\n"
          f"ML_file \\<open>{CHECKS}\\<close>\n\n"
          f"ML \\<open>Live_Node_Checks.run \\<^context> {ml_targets} {ml_bads}\\<close>\n\nend\n")

    # our own server, stopped by the client's shutdown below (and killed only if it lingers)
    server = subprocess.Popen(["isabelle", "server", "-n", "live_node_h"], stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True, bufsize=1)
    assert server.stdout is not None
    print("SERVER:", server.stdout.readline().strip(), flush=True)
    cl = subprocess.Popen(["isabelle", "client", "-n", "live_node_h"], stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)

    def send(line: str) -> None:
        assert cl.stdin is not None
        cl.stdin.write(line + "\n")
        cl.stdin.flush()

    def until(pred, limit=1800):
        assert cl.stdout is not None
        t = time.time()
        while time.time() - t < limit:
            line = cl.stdout.readline()
            if not line:
                break
            # LIVE_NODE_ALLOW_BUILD=1 lets session_start build the heap (a mutant of the ML
            # sources needs that); otherwise a build is a surprise and aborts the run
            if (line.startswith("NOTE") and ("Running " in line or "Building " in line)
                    and os.environ.get("LIVE_NODE_ALLOW_BUILD") != "1"):
                print("ABORT: session_start would build:", line.strip()[:400], flush=True)
                send("shutdown")
                time.sleep(3)
                cl.kill()
                sys.exit(2)
            if pred(line):
                return line
        raise SystemExit("timeout")

    done = lambda l: l.startswith("FINISHED") or l.startswith("FAILED")
    ok = False
    try:
        send('session_start {"session": "Semantic_Embedding"}')
        line = until(done)
        if line.startswith("FAILED"):
            print(line, flush=True)
            return 1
        sid = json.loads(line.split(" ", 1)[1])["session_id"]
        send('use_theories {"session_id": "%s", "theories": ["%s"]}'
             % (sid, os.path.join(work, "Live_Node_Test")))
        res = json.loads(until(done).split(" ", 1)[1])
        nodes = res.get("nodes", [])
        print("NODES:", json.dumps([n.get("node_name") for n in nodes]), flush=True)
        passed = False
        for n in nodes:
            for m in n.get("messages", []):
                text = m.get("message", "")
                if "Live_Node_Checks" in text or m.get("kind") == "error":
                    print(m.get("kind"), text[:600], flush=True)
                if "Live_Node_Checks: all checks passed" in text:
                    passed = True
        home_node = f"~/{home_rel}/LN_Home.thy"
        h0 = any(n.get("node_name") == home_node for n in nodes)
        print("H0 the USER_HOME fixture has the folded node name:", h0, flush=True)
        ok = bool(res.get("ok")) and not res.get("errors") and passed and h0
        send('session_stop {"session_id": "%s"}' % sid)
        until(done)
    finally:
        try:
            send("shutdown")
        except BrokenPipeError:
            pass
        try:
            server.wait(timeout=30)
        except subprocess.TimeoutExpired:
            server.kill()
    print("Live_Node headless test:", "PASSED" if ok else "FAILED", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
