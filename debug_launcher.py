from Isabelle_RPC_Host import launch_server_, mk_logger_
import Isabelle_Semantic_Embedding

if __name__ == "__main__":
    # NOTE (Isabelle_RPC >= 0.4.0): there is no shared default address anymore.  For the
    # Isabelle side to reach THIS server, export RPC_Host=127.0.0.1:27182 to it --
    # otherwise it silently launches and uses its own per-session ephemeral host.
    addr = "127.0.0.1:27182"
    logger = mk_logger_(addr, None)
    launch_server_(addr, logger, debugging=True)