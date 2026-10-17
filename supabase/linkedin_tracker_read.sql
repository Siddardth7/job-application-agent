-- Read access to the linkedin schema for linkedin_tracker.html (REST only exposes `public`).
-- service_role only: the anon key must NOT be able to read your LinkedIn contacts/messages.
-- Writes go through the existing public.save_contact_state RPC.
drop function if exists public.linkedin_tracker_contacts();
create function public.linkedin_tracker_contacts()
returns table (
  key text, profile_url text, full_name text, company text, title text, connected_on timestamptz,
  is_connection boolean, msg_count integer, msg_sent integer, msg_recv integer, last_msg_at timestamptz, last_msg_direction text,
  last_invite_at timestamptz, relevance text[],
  stage text, important boolean, needs_reply boolean, awaiting_reply boolean, poc_secured boolean,
  tags text[], notes text, follow_up_date date, relationship_score integer, resolved_at timestamptz, state_updated_at timestamptz
)
language sql security definer set search_path = ''
as $$
  select c.key, c.profile_url, c.full_name, c.company, c.title, c.connected_on,
         c.is_connection, c.msg_count, c.msg_sent, c.msg_recv, c.last_msg_at, c.last_msg_direction, c.last_invite_at, c.relevance,
         coalesce(s.stage,'none'), coalesce(s.important,false), coalesce(s.needs_reply,false),
         coalesce(s.awaiting_reply,false), coalesce(s.poc_secured,false),
         coalesce(s.tags,'{}'), coalesce(s.notes,''), s.follow_up_date, s.relationship_score, s.resolved_at, s.updated_at
  from linkedin.contacts c left join linkedin.contact_state s using (key) order by c.key;
$$;
revoke all on function public.linkedin_tracker_contacts() from public, anon, authenticated;
grant execute on function public.linkedin_tracker_contacts() to service_role;
