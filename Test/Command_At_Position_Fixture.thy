(*
  A command keyword that only a context importing this theory knows.  Command_At_Position_Test
  uses it after a definition: cutting that file on disk keeps the two commands apart only
  under a keyword table that has cap_fixture_cmd; without it the use glues onto the
  definition before it.
*)
theory Command_At_Position_Fixture
  imports Main
  keywords "cap_fixture_cmd" :: thy_decl
begin

ML \<open>
val _ =
  Outer_Syntax.command \<^command_keyword>\<open>cap_fixture_cmd\<close> "a command that does nothing"
    (Parse.name >> K (Toplevel.theory I))
\<close>

end
