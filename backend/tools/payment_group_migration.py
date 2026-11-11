"""088 SQL proof checks. Standalone migration helper, with no application imports."""

from __future__ import annotations

from alembic import op

TABLES = (
    "fp_payment_groups",
    "fp_payment_group_entries",
    "fp_payer_tip_entries",
    "fp_tip_run_sources",
    "fp_equal_split_plans",
    "fp_equal_split_parts",
    "fp_equal_split_part_payments",
    "fp_equal_split_plan_actions",
)


def install_guards() -> None:
    for table in TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION fp_reject_cash_mutation()"
        )
        op.execute(
            f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table} FOR EACH STATEMENT EXECUTE FUNCTION fp_reject_cash_mutation()"
        )
    op.execute("""
    CREATE FUNCTION fp_payment_original_unit(v uuid, oid uuid, lid text, unit_index integer) RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
    DECLARE original fp_orders; line jsonb; qty integer; gross bigint; tax bigint; paid bigint; assigned fp_service_unit_assignments; tab uuid; cancelled boolean; virtual_paid bigint;
    BEGIN
      SELECT * INTO original FROM fp_orders WHERE id=oid AND venue_id=v;
      IF original.id IS NULL OR unit_index<0 THEN RAISE EXCEPTION 'Original unit scope missing'; END IF;
      IF lid='tip' THEN
        IF unit_index!=0 OR original.tip_cents<=0 THEN RAISE EXCEPTION 'Original tip unit missing'; END IF;
        gross:=original.tip_cents; tax:=0;
        SELECT guest_tab_id INTO tab FROM fp_service_round_children WHERE order_id=oid AND venue_id=v;
        SELECT EXISTS(SELECT 1 FROM fp_cancellation_units WHERE order_id=oid AND kind='tip') INTO cancelled;
      ELSE
        SELECT element INTO line FROM jsonb_array_elements(original.lines) WITH ORDINALITY AS item(element,ordinality)
          WHERE fp_cash_line_id(oid,ordinality-1,element)::text=lid;
        qty:=(line->>'quantity')::integer;
        IF line IS NULL OR qty IS NULL OR unit_index>=qty THEN RAISE EXCEPTION 'Original unit missing'; END IF;
        gross:=(line->>'total_cents')::bigint*(unit_index+1)/qty-(line->>'total_cents')::bigint*unit_index/qty;
        tax:=(line->>'tax_cents')::bigint*(unit_index+1)/qty-(line->>'tax_cents')::bigint*unit_index/qty;
        SELECT * INTO assigned FROM fp_service_unit_assignments WHERE venue_id=v AND order_id=oid AND line_id=lid::uuid AND unit=unit_index ORDER BY version DESC LIMIT 1;
        tab:=assigned.guest_tab_id;
        SELECT EXISTS(SELECT 1 FROM fp_cancellation_units WHERE order_id=oid AND line_id=lid::uuid AND unit=unit_index) INTO cancelled;
      END IF;
      SELECT coalesce(sum((allocation->>'amount_cents')::bigint),0) INTO paid FROM fp_cash_entries entry CROSS JOIN LATERAL jsonb_array_elements(entry.allocations) AS allocation
        WHERE entry.venue_id=v AND entry.order_id=oid AND entry.kind='sale' AND allocation->>'line_id'=lid AND (allocation->>'unit')::integer=unit_index;
      IF lid!='tip' AND original.voucher_cents>0 AND NOT EXISTS(SELECT 1 FROM fp_cash_entries WHERE order_id=oid AND kind='sale' AND method='voucher') THEN
        WITH original_units AS (
          SELECT fp_cash_line_id(oid,ordinality-1,element)::text AS line_id, idx AS unit,
            (element->>'total_cents')::bigint*(idx+1)/(element->>'quantity')::integer-(element->>'total_cents')::bigint*idx/(element->>'quantity')::integer AS gross
          FROM jsonb_array_elements(original.lines) WITH ORDINALITY AS line_item(element,ordinality)
          CROSS JOIN LATERAL generate_series(0,(element->>'quantity')::integer-1) AS idx
        ), weights AS (
          SELECT u.line_id,u.unit,greatest(0,u.gross-coalesce((SELECT sum((a->>'amount_cents')::bigint) FROM fp_cash_entries e CROSS JOIN LATERAL jsonb_array_elements(e.allocations) a WHERE e.order_id=oid AND e.kind='sale' AND a->>'line_id'=u.line_id AND (a->>'unit')::integer=u.unit),0)) AS weight FROM original_units u
        ), positive AS (SELECT *,sum(weight) OVER() AS total FROM weights WHERE weight>0), amounts AS (
          SELECT *,original.voucher_cents*weight/total AS floor_cents, row_number() OVER(ORDER BY -(original.voucher_cents*weight%total),line_id,unit) AS rank FROM positive
        ), distributed AS (
          SELECT *,floor_cents+(CASE WHEN rank<=original.voucher_cents-sum(floor_cents) OVER() THEN 1 ELSE 0 END) AS cents FROM amounts
        ) SELECT cents INTO virtual_paid FROM distributed WHERE line_id=lid AND unit=unit_index;
        paid:=paid+coalesce(virtual_paid,0);
      END IF;
      RETURN jsonb_build_object('gross_cents',gross,'tax_cents',tax,'paid_cents',paid,'cancelled',cancelled,'assignment_id',assigned.id,'assignment_version',assigned.version,'guest_tab_id',tab);
    END $$
    """)
    op.execute("""
    CREATE FUNCTION fp_guard_payment_scope() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE payload jsonb:=to_jsonb(NEW); venue fp_venues; member_role text; cash_session fp_cash_sessions;
    BEGIN
      SELECT * INTO venue FROM fp_venues WHERE id=NEW.venue_id FOR NO KEY UPDATE;
      IF venue.id IS NULL THEN RAISE EXCEPTION 'Payment venue missing'; END IF;
      IF payload ? 'currency' AND payload->>'currency' IS DISTINCT FROM venue.currency THEN RAISE EXCEPTION 'Payment currency scope differs'; END IF;
      IF payload ? 'request_hash' AND length(payload->>'request_hash')!=64 THEN RAISE EXCEPTION 'Payment command hash missing'; END IF;
      IF payload ? 'actor_id' THEN
        SELECT role INTO member_role FROM fp_memberships WHERE venue_id=venue.id AND user_id=(payload->>'actor_id')::uuid AND active;
        IF member_role IS NULL OR member_role NOT IN ('manager','service') THEN RAISE EXCEPTION 'Payment actor must serve this venue'; END IF;
      END IF;
      IF payload->>'payer_tab_id' IS NOT NULL AND NOT EXISTS(SELECT 1 FROM fp_guest_tabs WHERE id=(payload->>'payer_tab_id')::uuid AND venue_id=venue.id) THEN RAISE EXCEPTION 'Payer belongs to another venue'; END IF;
      IF payload ? 'session_id' THEN
        SELECT * INTO cash_session FROM fp_cash_sessions WHERE id=(payload->>'session_id')::uuid AND venue_id=venue.id FOR UPDATE;
        IF cash_session.id IS NULL OR cash_session.status!='open' OR (member_role!='manager' AND cash_session.operator_id IS DISTINCT FROM (payload->>'actor_id')::uuid) THEN RAISE EXCEPTION 'Payment needs own open cash session'; END IF;
      END IF;
      RETURN NEW;
    END $$
    """)
    for table in TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_scope BEFORE INSERT ON {table} FOR EACH ROW EXECUTE FUNCTION fp_guard_payment_scope()"
        )
    op.execute("""
    CREATE FUNCTION fp_validate_payment_group() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE gid uuid; grp fp_payment_groups; linked fp_payment_group_entries; entry fp_cash_entries; source jsonb; actual jsonb; allocation jsonb; previous_paid bigint; allocated bigint; child_sum bigint; tip_sum bigint; order_count integer; unit_count integer; parts_sum bigint; plan_count integer;
    BEGIN
      IF TG_TABLE_NAME='fp_payment_groups' THEN gid:=NEW.id;
      ELSIF TG_TABLE_NAME='fp_payer_tip_entries' THEN
        IF NEW.kind='returned' THEN RETURN NEW; END IF;
        gid:=NEW.payment_group_id;
      ELSE gid:=NEW.group_id; END IF;
      SELECT * INTO grp FROM fp_payment_groups WHERE id=gid;
      IF grp.id IS NULL THEN RAISE EXCEPTION 'Payment group missing'; END IF;
      IF NEW.venue_id IS DISTINCT FROM grp.venue_id THEN RAISE EXCEPTION 'Payment group scope differs'; END IF;
      IF jsonb_typeof(grp.allocations) IS DISTINCT FROM 'array' OR jsonb_typeof(grp.source_snapshot) IS DISTINCT FROM 'array' OR grp.amount_cents>100000000 OR grp.new_tip_cents>100000 OR jsonb_array_length(grp.allocations)>1000 THEN RAISE EXCEPTION 'Invalid group selection'; END IF;
      SELECT count(*),coalesce(sum(e.amount_cents),0) INTO order_count,child_sum FROM fp_payment_group_entries l JOIN fp_cash_entries e ON e.id=l.entry_id WHERE l.group_id=gid;
      IF order_count>50 OR child_sum!=grp.receipt_amount_cents THEN RAISE EXCEPTION 'Incomplete original payment children'; END IF;
      SELECT coalesce(sum(amount_cents),0) INTO tip_sum FROM fp_payer_tip_entries WHERE payment_group_id=gid AND kind='received';
      IF tip_sum!=grp.new_tip_cents THEN RAISE EXCEPTION 'Incomplete additive tip evidence'; END IF;
      IF grp.receipt_amount_cents=0 AND (grp.new_tip_cents<=0 OR grp.payer_tab_id IS NULL OR grp.quote->>'mode' IS DISTINCT FROM 'tip_only') THEN RAISE EXCEPTION 'Tip-only requires explicit guest context'; END IF;
      SELECT coalesce(sum((a->>'amount_cents')::bigint),0),count(*) INTO allocated,unit_count FROM jsonb_array_elements(grp.allocations) a;
      IF allocated!=grp.receipt_amount_cents OR unit_count!=jsonb_array_length(grp.source_snapshot) THEN RAISE EXCEPTION 'Group allocations do not conserve cents'; END IF;
      IF EXISTS(SELECT 1 FROM jsonb_array_elements(grp.allocations) a GROUP BY a->>'order_id',a->>'line_id',a->>'unit' HAVING count(*)!=1) THEN RAISE EXCEPTION 'Duplicate original group unit'; END IF;
      FOR linked IN SELECT * FROM fp_payment_group_entries WHERE group_id=gid LOOP
        SELECT * INTO entry FROM fp_cash_entries WHERE id=linked.entry_id;
        IF linked.venue_id IS DISTINCT FROM grp.venue_id OR entry.venue_id IS DISTINCT FROM grp.venue_id OR entry.order_id IS DISTINCT FROM linked.order_id OR entry.session_id IS DISTINCT FROM grp.session_id OR entry.actor_id IS DISTINCT FROM grp.actor_id OR entry.currency IS DISTINCT FROM grp.currency OR entry.method!='cash' OR entry.kind!='sale' OR entry.received_cents IS NOT NULL OR entry.change_cents IS NOT NULL THEN RAISE EXCEPTION 'Original cash child differs from group'; END IF;
        IF (SELECT coalesce(jsonb_agg(a-'order_id' ORDER BY a->>'line_id',(a->>'unit')::integer),'[]'::jsonb) FROM jsonb_array_elements(grp.allocations) a WHERE a->>'order_id'=linked.order_id::text)
          IS DISTINCT FROM (SELECT coalesce(jsonb_agg(a ORDER BY a->>'line_id',(a->>'unit')::integer),'[]'::jsonb) FROM jsonb_array_elements(entry.allocations) a) THEN RAISE EXCEPTION 'Group original allocation differs'; END IF;
      END LOOP;
      FOR allocation IN SELECT * FROM jsonb_array_elements(grp.allocations) LOOP
        IF NOT(allocation ?& ARRAY['order_id','line_id','unit','amount_cents','tax_cents','kind','name']) OR NOT coalesce((allocation->>'amount_cents')::bigint>0,false) THEN RAISE EXCEPTION 'Incomplete group unit'; END IF;
        SELECT s INTO source FROM jsonb_array_elements(grp.source_snapshot) s WHERE s->>'order_id'=allocation->>'order_id' AND s->>'line_id'=allocation->>'line_id' AND s->>'unit'=allocation->>'unit';
        actual:=fp_payment_original_unit(grp.venue_id,(allocation->>'order_id')::uuid,allocation->>'line_id',(allocation->>'unit')::integer);
        IF source IS NULL OR NOT(source ?& ARRAY['gross_cents','tax_cents','paid_cents','cancelled','assignment_id','assignment_version','guest_tab_id','selected_cents']) THEN RAISE EXCEPTION 'Group original snapshot missing'; END IF;
        previous_paid:=(actual->>'paid_cents')::bigint-(allocation->>'amount_cents')::bigint;
        IF source->'gross_cents' IS DISTINCT FROM actual->'gross_cents' OR source->'tax_cents' IS DISTINCT FROM actual->'tax_cents' OR source->'assignment_id' IS DISTINCT FROM actual->'assignment_id' OR source->'assignment_version' IS DISTINCT FROM actual->'assignment_version' OR source->'guest_tab_id' IS DISTINCT FROM actual->'guest_tab_id' OR (actual->>'cancelled')::boolean IS DISTINCT FROM false OR (source->>'paid_cents')::bigint IS DISTINCT FROM previous_paid OR (source->>'selected_cents')::bigint IS DISTINCT FROM (allocation->>'amount_cents')::bigint THEN RAISE EXCEPTION 'Group original source changed'; END IF;
      END LOOP;
      SELECT coalesce(sum(amount_cents),0) INTO parts_sum FROM fp_equal_split_part_payments WHERE group_id=gid;
      SELECT count(DISTINCT part.plan_id) INTO plan_count FROM fp_equal_split_part_payments paid_part JOIN fp_equal_split_parts part ON part.id=paid_part.part_id WHERE paid_part.group_id=gid;
      IF plan_count>1 THEN RAISE EXCEPTION 'Payment group cannot combine unrelated split plans'; END IF;
      IF (grp.quote->>'mode'='parts' AND parts_sum!=grp.receipt_amount_cents) OR (grp.quote->>'mode'!='parts' AND parts_sum!=0) THEN RAISE EXCEPTION 'Incomplete plan payment links'; END IF;
      RETURN NEW;
    END $$
    """)
    for table in (
        "fp_payment_groups",
        "fp_payment_group_entries",
        "fp_payer_tip_entries",
        "fp_equal_split_part_payments",
    ):
        op.execute(
            f"CREATE CONSTRAINT TRIGGER {table}_complete AFTER INSERT ON {table} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION fp_validate_payment_group()"
        )
    op.execute("""
    CREATE FUNCTION fp_validate_payer_tip() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE grp fp_payment_groups; original fp_payer_tip_entries; total bigint; available bigint; actor_role text;
    BEGIN
      SELECT * INTO grp FROM fp_payment_groups WHERE id=NEW.payment_group_id;
      IF grp.id IS NULL OR grp.venue_id IS DISTINCT FROM NEW.venue_id OR grp.currency IS DISTINCT FROM NEW.currency OR grp.payer_tab_id IS DISTINCT FROM NEW.payer_tab_id OR grp.payer_label IS DISTINCT FROM NEW.payer_label THEN RAISE EXCEPTION 'Tip group scope differs'; END IF;
      IF NEW.kind='received' AND NEW.recipient_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM fp_memberships WHERE venue_id=NEW.venue_id AND user_id=NEW.recipient_id AND active) THEN RAISE EXCEPTION 'Tip recipient missing'; END IF;
      IF NEW.kind='received' THEN
        IF NEW.amount_cents IS DISTINCT FROM grp.new_tip_cents OR NEW.session_id IS DISTINCT FROM grp.session_id OR NEW.actor_id IS DISTINCT FROM grp.actor_id OR NEW.recipient_id::text IS DISTINCT FROM coalesce(grp.quote->>'recipient_id',grp.actor_id::text) THEN RAISE EXCEPTION 'Received tip differs from cash group'; END IF;
      ELSE
        SELECT role INTO actor_role FROM fp_memberships WHERE venue_id=NEW.venue_id AND user_id=NEW.actor_id AND active;
        SELECT * INTO original FROM fp_payer_tip_entries WHERE id=NEW.original_id;
        IF actor_role IS DISTINCT FROM 'manager' OR length(trim(NEW.reason))<3 OR original.kind IS DISTINCT FROM 'received' OR original.venue_id IS DISTINCT FROM NEW.venue_id OR original.payment_group_id IS DISTINCT FROM NEW.payment_group_id OR original.recipient_id IS DISTINCT FROM NEW.recipient_id THEN RAISE EXCEPTION 'Tip return requires manager and original source'; END IF;
        IF EXISTS(SELECT 1 FROM fp_tip_run_sources WHERE payer_tip_id=original.id) THEN RAISE EXCEPTION 'Distributed tip cannot be returned'; END IF;
        SELECT original.amount_cents+coalesce(sum(amount_cents),0)+NEW.amount_cents INTO total FROM fp_payer_tip_entries WHERE original_id=original.id;
        IF total<0 THEN RAISE EXCEPTION 'Tip return exceeds original source'; END IF;
        SELECT coalesce((SELECT sum(amount_cents) FROM fp_cash_entries WHERE session_id=NEW.session_id AND method='cash'),0)+coalesce((SELECT sum(amount_cents) FROM fp_payer_tip_entries WHERE session_id=NEW.session_id),0)+NEW.amount_cents INTO available;
        IF available<0 THEN RAISE EXCEPTION 'Tip return exceeds drawer cash'; END IF;
      END IF;
      RETURN NEW;
    END $$
    """)
    op.execute(
        "CREATE TRIGGER fp_payer_tip_validate BEFORE INSERT ON fp_payer_tip_entries FOR EACH ROW EXECUTE FUNCTION fp_validate_payer_tip()"
    )
    op.execute("""
    CREATE FUNCTION fp_validate_equal_plan() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE pid uuid; plan fp_equal_split_plans; previous fp_equal_split_plans; part fp_equal_split_parts; source jsonb; budget jsonb; target_sum bigint; count_parts integer; cell_count integer; cents bigint; actual jsonb;
    BEGIN
      IF TG_TABLE_NAME='fp_equal_split_plans' THEN pid:=NEW.id; ELSE pid:=NEW.plan_id; END IF;
      SELECT * INTO plan FROM fp_equal_split_plans WHERE id=pid;
      IF plan.id IS NULL OR plan.venue_id IS DISTINCT FROM NEW.venue_id OR jsonb_typeof(plan.source_snapshot) IS DISTINCT FROM 'array' OR jsonb_array_length(plan.source_snapshot)>1000 THEN RAISE EXCEPTION 'Invalid plan source'; END IF;
      IF plan.supersedes_id IS NULL THEN
        IF plan.root_plan_id!=plan.id OR plan.revision!=1 THEN RAISE EXCEPTION 'Invalid initial plan revision'; END IF;
      ELSE
        SELECT * INTO previous FROM fp_equal_split_plans WHERE id=plan.supersedes_id;
        IF previous.venue_id IS DISTINCT FROM plan.venue_id OR plan.root_plan_id IS DISTINCT FROM previous.root_plan_id OR plan.revision IS DISTINCT FROM previous.revision+1 OR length(trim(plan.reason))<3 OR NOT EXISTS(SELECT 1 FROM fp_equal_split_plan_actions WHERE plan_id=previous.id AND next_plan_id=plan.id AND action='supersede') THEN RAISE EXCEPTION 'Plan successor proof missing'; END IF;
        IF EXISTS(SELECT 1 FROM jsonb_array_elements(plan.source_snapshot) s WHERE NOT EXISTS(SELECT 1 FROM jsonb_array_elements(previous.source_snapshot) p WHERE (p->>'order_id',p->>'line_id',p->>'unit')=(s->>'order_id',s->>'line_id',s->>'unit'))) THEN RAISE EXCEPTION 'Successor expands original plan scope'; END IF;
      END IF;
      SELECT count(*),coalesce(sum(target_cents),0),coalesce(sum(jsonb_array_length(unit_budgets)),0) INTO count_parts,target_sum,cell_count FROM fp_equal_split_parts WHERE plan_id=pid;
      IF count_parts<2 OR count_parts>100 OR target_sum!=plan.total_cents OR cell_count>10000 THEN RAISE EXCEPTION 'Incomplete plan participants'; END IF;
      FOR part IN SELECT * FROM fp_equal_split_parts WHERE plan_id=pid LOOP
        IF part.venue_id IS DISTINCT FROM plan.venue_id OR part.ordinal>=count_parts OR part.target_cents IS DISTINCT FROM plan.total_cents/count_parts+(CASE WHEN part.ordinal<plan.total_cents%count_parts THEN 1 ELSE 0 END) OR jsonb_typeof(part.unit_budgets) IS DISTINCT FROM 'array' THEN RAISE EXCEPTION 'Plan participant target differs'; END IF;
        SELECT coalesce(sum((b->>'amount_cents')::bigint),0) INTO cents FROM jsonb_array_elements(part.unit_budgets) b;
        IF cents!=part.target_cents OR EXISTS(SELECT 1 FROM jsonb_array_elements(part.unit_budgets) b GROUP BY b->>'order_id',b->>'line_id',b->>'unit' HAVING count(*)!=1) THEN RAISE EXCEPTION 'Plan participant budget differs'; END IF;
        FOR budget IN SELECT * FROM jsonb_array_elements(part.unit_budgets) LOOP
          IF NOT(budget ?& ARRAY['order_id','line_id','unit','amount_cents']) OR NOT coalesce((budget->>'amount_cents')::bigint>0,false) OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(plan.source_snapshot) s WHERE (s->>'order_id',s->>'line_id',s->>'unit')=(budget->>'order_id',budget->>'line_id',budget->>'unit')) THEN RAISE EXCEPTION 'Plan unit budget scope differs'; END IF;
        END LOOP;
      END LOOP;
      IF EXISTS(SELECT 1 FROM jsonb_array_elements(plan.source_snapshot) s GROUP BY s->>'order_id',s->>'line_id',s->>'unit' HAVING count(*)!=1) THEN RAISE EXCEPTION 'Duplicate plan source'; END IF;
      FOR source IN SELECT * FROM jsonb_array_elements(plan.source_snapshot) LOOP
        IF NOT(source ?& ARRAY['order_id','line_id','unit','selected_cents','gross_cents','tax_cents','paid_cents','assignment_id','assignment_version','guest_tab_id','cancelled']) THEN RAISE EXCEPTION 'Plan source incomplete'; END IF;
        SELECT coalesce(sum((b->>'amount_cents')::bigint),0) INTO cents FROM fp_equal_split_parts p CROSS JOIN LATERAL jsonb_array_elements(p.unit_budgets) b WHERE p.plan_id=pid AND (b->>'order_id',b->>'line_id',b->>'unit')=(source->>'order_id',source->>'line_id',source->>'unit');
        IF cents IS DISTINCT FROM (source->>'selected_cents')::bigint OR cents<=0 OR cents>(source->>'gross_cents')::bigint-(source->>'paid_cents')::bigint THEN RAISE EXCEPTION 'Plan original cent budgets differ'; END IF;
        actual:=fp_payment_original_unit(plan.venue_id,(source->>'order_id')::uuid,source->>'line_id',(source->>'unit')::integer);
        IF source->'gross_cents' IS DISTINCT FROM actual->'gross_cents' OR source->'tax_cents' IS DISTINCT FROM actual->'tax_cents' OR source->'assignment_id' IS DISTINCT FROM actual->'assignment_id' OR source->'assignment_version' IS DISTINCT FROM actual->'assignment_version' OR source->'guest_tab_id' IS DISTINCT FROM actual->'guest_tab_id' OR (actual->>'cancelled')::boolean IS DISTINCT FROM false OR source->'paid_cents' IS DISTINCT FROM actual->'paid_cents' THEN RAISE EXCEPTION 'Plan original source changed'; END IF;
      END LOOP;
      RETURN NEW;
    END $$
    """)
    for table in ("fp_equal_split_plans", "fp_equal_split_parts"):
        op.execute(
            f"CREATE CONSTRAINT TRIGGER {table}_complete AFTER INSERT ON {table} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION fp_validate_equal_plan()"
        )
    op.execute("""
    CREATE FUNCTION fp_validate_equal_payment() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE part fp_equal_split_parts; plan fp_equal_split_plans; grp fp_payment_groups; allocation jsonb; budget bigint; used bigint; original_allocation bigint; shared bigint; original jsonb; actual jsonb; own_paid bigint;
    BEGIN
      SELECT * INTO part FROM fp_equal_split_parts WHERE id=NEW.part_id;
      SELECT * INTO plan FROM fp_equal_split_plans WHERE id=part.plan_id;
      SELECT * INTO grp FROM fp_payment_groups WHERE id=NEW.group_id;
      IF part.venue_id IS DISTINCT FROM NEW.venue_id OR grp.venue_id IS DISTINCT FROM NEW.venue_id OR grp.quote->>'mode' IS DISTINCT FROM 'parts' OR NOT coalesce(grp.quote->'part_ids' ? NEW.part_id::text,false) OR EXISTS(SELECT 1 FROM fp_equal_split_plan_actions WHERE plan_id=plan.id) THEN RAISE EXCEPTION 'Plan payment scope or lifecycle differs'; END IF;
      IF (SELECT coalesce(sum(amount_cents),0) FROM fp_equal_split_part_payments WHERE part_id=part.id)>part.target_cents OR (SELECT coalesce(sum((a->>'amount_cents')::bigint),0) FROM jsonb_array_elements(NEW.allocations) a) IS DISTINCT FROM NEW.amount_cents THEN RAISE EXCEPTION 'Plan payment exceeds participant target'; END IF;
      IF EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.allocations) a GROUP BY a->>'order_id',a->>'line_id',a->>'unit' HAVING count(*)!=1) THEN RAISE EXCEPTION 'Duplicate plan payment unit'; END IF;
      FOR allocation IN SELECT * FROM jsonb_array_elements(NEW.allocations) LOOP
        IF NOT(allocation ?& ARRAY['order_id','line_id','unit','amount_cents','entry_id']) OR NOT coalesce((allocation->>'amount_cents')::bigint>0,false) THEN RAISE EXCEPTION 'Incomplete plan payment'; END IF;
        SELECT (b->>'amount_cents')::bigint INTO budget FROM jsonb_array_elements(part.unit_budgets) b WHERE (b->>'order_id',b->>'line_id',b->>'unit')=(allocation->>'order_id',allocation->>'line_id',allocation->>'unit');
        SELECT coalesce(sum((a->>'amount_cents')::bigint),0) INTO used FROM fp_equal_split_part_payments p CROSS JOIN LATERAL jsonb_array_elements(p.allocations) a WHERE p.part_id=part.id AND (a->>'order_id',a->>'line_id',a->>'unit')=(allocation->>'order_id',allocation->>'line_id',allocation->>'unit');
        IF budget IS NULL OR used>budget OR NOT EXISTS(SELECT 1 FROM fp_payment_group_entries WHERE group_id=grp.id AND entry_id=(allocation->>'entry_id')::uuid AND order_id=(allocation->>'order_id')::uuid) THEN RAISE EXCEPTION 'Plan payment unit exceeds original budget'; END IF;
        SELECT (a->>'amount_cents')::bigint INTO original_allocation FROM jsonb_array_elements(grp.allocations) a WHERE (a->>'order_id',a->>'line_id',a->>'unit')=(allocation->>'order_id',allocation->>'line_id',allocation->>'unit');
        SELECT coalesce(sum((a->>'amount_cents')::bigint),0) INTO shared FROM fp_equal_split_part_payments p CROSS JOIN LATERAL jsonb_array_elements(p.allocations) a WHERE p.group_id=grp.id AND (a->>'order_id',a->>'line_id',a->>'unit')=(allocation->>'order_id',allocation->>'line_id',allocation->>'unit');
        IF shared IS DISTINCT FROM original_allocation THEN RAISE EXCEPTION 'Plan payments do not partition actual original allocation'; END IF;
      END LOOP;
      FOR original IN SELECT * FROM jsonb_array_elements(plan.source_snapshot) LOOP
        actual:=fp_payment_original_unit(plan.venue_id,(original->>'order_id')::uuid,original->>'line_id',(original->>'unit')::integer);
        SELECT coalesce(sum((a->>'amount_cents')::bigint),0) INTO own_paid FROM fp_equal_split_part_payments p JOIN fp_equal_split_parts participant ON participant.id=p.part_id CROSS JOIN LATERAL jsonb_array_elements(p.allocations) a WHERE participant.plan_id=plan.id AND (a->>'order_id',a->>'line_id',a->>'unit')=(original->>'order_id',original->>'line_id',original->>'unit');
        IF (original->>'paid_cents')::bigint+own_paid IS DISTINCT FROM (actual->>'paid_cents')::bigint OR original->'assignment_id' IS DISTINCT FROM actual->'assignment_id' OR original->'assignment_version' IS DISTINCT FROM actual->'assignment_version' OR original->'guest_tab_id' IS DISTINCT FROM actual->'guest_tab_id' OR (actual->>'cancelled')::boolean IS DISTINCT FROM false THEN RAISE EXCEPTION 'Foreign payment or changed source invalidates plan'; END IF;
      END LOOP;
      RETURN NEW;
    END $$
    """)
    op.execute(
        "CREATE CONSTRAINT TRIGGER fp_equal_payment_complete AFTER INSERT ON fp_equal_split_part_payments DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION fp_validate_equal_payment()"
    )
    op.execute("""
    CREATE FUNCTION fp_validate_equal_action() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE plan fp_equal_split_plans; successor fp_equal_split_plans;
    BEGIN
      SELECT * INTO plan FROM fp_equal_split_plans WHERE id=NEW.plan_id;
      IF plan.venue_id IS DISTINCT FROM NEW.venue_id OR length(trim(NEW.reason))<3 THEN RAISE EXCEPTION 'Plan action scope or reason missing'; END IF;
      IF NEW.action='abandon' THEN
        IF NEW.next_plan_id IS NOT NULL THEN RAISE EXCEPTION 'Abandoned plan cannot name successor'; END IF;
      ELSIF NEW.action='supersede' THEN
        SELECT * INTO successor FROM fp_equal_split_plans WHERE id=NEW.next_plan_id;
        IF successor.venue_id IS DISTINCT FROM plan.venue_id OR successor.supersedes_id IS DISTINCT FROM plan.id OR successor.revision IS DISTINCT FROM plan.revision+1 THEN RAISE EXCEPTION 'Plan action successor differs'; END IF;
      ELSE RAISE EXCEPTION 'Unknown plan action'; END IF;
      RETURN NEW;
    END $$
    """)
    op.execute(
        "CREATE CONSTRAINT TRIGGER fp_equal_action_complete AFTER INSERT ON fp_equal_split_plan_actions DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION fp_validate_equal_action()"
    )
    op.execute("""
    CREATE FUNCTION fp_validate_tip_run_source() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE run fp_tip_runs; original fp_orders; tip fp_payer_tip_entries; available bigint; source_at timestamptz; source_zone text;
    BEGIN
      SELECT * INTO run FROM fp_tip_runs WHERE id=NEW.run_id;
      IF run.venue_id IS DISTINCT FROM NEW.venue_id OR length(NEW.source_hash)!=64 OR jsonb_typeof(NEW.source_snapshot) IS DISTINCT FROM 'object' THEN RAISE EXCEPTION 'Tip distribution source scope differs'; END IF;
      IF NEW.kind='order' THEN
        SELECT * INTO original FROM fp_orders WHERE id=NEW.order_id;
        available:=original.tip_cents-original.tip_refunded_cents; source_at:=original.paid_at;
        IF NEW.source_snapshot->>'order_id' IS DISTINCT FROM original.id::text THEN RAISE EXCEPTION 'Tip source snapshot identity differs'; END IF;
        IF original.venue_id IS DISTINCT FROM NEW.venue_id OR original.paid_at IS NULL OR original.tip_run_id IS DISTINCT FROM run.id OR EXISTS(SELECT 1 FROM fp_cancellation_units WHERE order_id=original.id AND kind='tip') THEN RAISE EXCEPTION 'Original tip is not distributable'; END IF;
      ELSE
        SELECT * INTO tip FROM fp_payer_tip_entries WHERE id=NEW.payer_tip_id;
        SELECT tip.amount_cents+coalesce(sum(amount_cents),0) INTO available FROM fp_payer_tip_entries WHERE original_id=tip.id;
        source_at:=tip.created_at;
        IF NEW.source_snapshot->>'payer_tip_id' IS DISTINCT FROM tip.id::text OR NEW.source_snapshot->>'payment_group_id' IS DISTINCT FROM tip.payment_group_id::text THEN RAISE EXCEPTION 'Payer tip snapshot identity differs'; END IF;
        IF tip.venue_id IS DISTINCT FROM NEW.venue_id OR tip.kind IS DISTINCT FROM 'received' THEN RAISE EXCEPTION 'Payer tip source differs'; END IF;
      END IF;
      SELECT timezone INTO source_zone FROM fp_venues WHERE id=NEW.venue_id;
      IF source_at IS NULL OR (source_at AT TIME ZONE source_zone)::date<run.period_start OR (source_at AT TIME ZONE source_zone)::date>run.period_end OR NEW.source_snapshot->>'timezone' IS DISTINCT FROM source_zone THEN RAISE EXCEPTION 'Tip source falls outside recorded venue period'; END IF;
      IF available IS DISTINCT FROM NEW.amount_cents OR NEW.amount_cents<=0 OR (NEW.source_snapshot->>'amount_cents')::bigint IS DISTINCT FROM available THEN RAISE EXCEPTION 'Tip distribution must consume full actual remainder'; END IF;
      IF (SELECT coalesce(sum(amount_cents),0) FROM fp_tip_run_sources WHERE run_id=run.id) IS DISTINCT FROM run.total_cents OR (SELECT coalesce(sum(share_cents),0) FROM fp_tip_shares WHERE run_id=run.id) IS DISTINCT FROM run.total_cents THEN RAISE EXCEPTION 'Tip distribution sources and shares do not conserve cents'; END IF;
      RETURN NEW;
    END $$
    """)
    op.execute(
        "CREATE CONSTRAINT TRIGGER fp_tip_run_source_complete AFTER INSERT ON fp_tip_run_sources DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION fp_validate_tip_run_source()"
    )
    op.execute("""
    CREATE FUNCTION fp_validate_tip_run_complete() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE rid uuid; run fp_tip_runs; source_total bigint; source_orders integer; share_total bigint;
    BEGIN
      IF TG_TABLE_NAME='fp_tip_runs' THEN rid:=NEW.id; ELSE rid:=NEW.run_id; END IF;
      SELECT * INTO run FROM fp_tip_runs WHERE id=rid;
      SELECT coalesce(sum(amount_cents),0),count(*) FILTER(WHERE kind='order') INTO source_total,source_orders FROM fp_tip_run_sources WHERE run_id=rid;
      SELECT coalesce(sum(share_cents),0) INTO share_total FROM fp_tip_shares WHERE run_id=rid;
      IF run.id IS NULL OR run.total_cents<=0 OR run.total_cents IS DISTINCT FROM source_total OR run.total_cents IS DISTINCT FROM share_total OR run.orders IS DISTINCT FROM source_orders THEN RAISE EXCEPTION 'Tip run requires complete original sources and shares'; END IF;
      RETURN NEW;
    END $$
    """)
    for table in ("fp_tip_runs", "fp_tip_shares"):
        op.execute(
            f"CREATE CONSTRAINT TRIGGER {table}_088_sources AFTER INSERT ON {table} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION fp_validate_tip_run_complete()"
        )
    op.execute("""
    CREATE FUNCTION fp_guard_order_tip_source() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.tip_run_id IS NOT DISTINCT FROM OLD.tip_run_id THEN RETURN NEW; END IF;
      IF OLD.tip_run_id IS NOT NULL OR NEW.tip_run_id IS NULL OR NOT EXISTS(SELECT 1 FROM fp_tip_run_sources WHERE order_id=NEW.id AND venue_id=NEW.venue_id AND run_id=NEW.tip_run_id AND kind='order') THEN RAISE EXCEPTION 'Original tip assignment requires immutable source evidence'; END IF;
      RETURN NEW;
    END $$
    """)
    op.execute(
        "CREATE CONSTRAINT TRIGGER fp_orders_088_tip_source AFTER UPDATE ON fp_orders DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION fp_guard_order_tip_source()"
    )
    op.execute("""
    CREATE FUNCTION fp_guard_group_cash_count() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE expected bigint;
    BEGIN
      IF OLD.status='closed' AND (to_jsonb(NEW)-'updated_at') IS DISTINCT FROM (to_jsonb(OLD)-'updated_at') THEN RAISE EXCEPTION 'Closed cash count is immutable'; END IF;
      IF NEW.status IN ('counted','closed') THEN
        SELECT coalesce((SELECT sum(amount_cents) FROM fp_cash_entries WHERE session_id=NEW.id AND method='cash'),0)+coalesce((SELECT sum(amount_cents) FROM fp_payer_tip_entries WHERE session_id=NEW.id),0) INTO expected;
        IF NEW.expected_cents IS DISTINCT FROM expected OR NEW.counted_cents IS NULL OR NEW.difference_cents IS DISTINCT FROM NEW.counted_cents-expected THEN RAISE EXCEPTION 'Cash count differs from actual receipts and tips'; END IF;
      END IF;
      RETURN NEW;
    END $$
    """)
    op.execute(
        "CREATE TRIGGER fp_cash_group_count BEFORE UPDATE ON fp_cash_sessions FOR EACH ROW EXECUTE FUNCTION fp_guard_group_cash_count()"
    )


def remove_guards() -> None:
    op.execute("DROP TRIGGER fp_orders_088_tip_source ON fp_orders")
    op.execute("DROP FUNCTION fp_guard_order_tip_source()")
    for table in ("fp_tip_runs", "fp_tip_shares"):
        op.execute(f"DROP TRIGGER {table}_088_sources ON {table}")
    op.execute("DROP FUNCTION fp_validate_tip_run_complete()")
    op.execute("DROP TRIGGER fp_cash_group_count ON fp_cash_sessions")
    op.execute("DROP FUNCTION fp_guard_group_cash_count()")
    for name in (
        "fp_validate_tip_run_source",
        "fp_validate_equal_action",
        "fp_validate_equal_payment",
        "fp_validate_equal_plan",
        "fp_validate_payer_tip",
        "fp_validate_payment_group",
        "fp_guard_payment_scope",
    ):
        op.execute(f"DROP FUNCTION {name}() CASCADE")
    op.execute("DROP FUNCTION fp_payment_original_unit(uuid,uuid,text,integer)")
    for table in TABLES:
        op.execute(f"DROP TRIGGER {table}_immutable ON {table}")
        op.execute(f"DROP TRIGGER {table}_no_truncate ON {table}")
