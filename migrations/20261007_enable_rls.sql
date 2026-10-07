-- Ferme l'acces direct PostgREST aux donnees metier FanMilk.
-- Le backend Flask utilise la connexion PostgreSQL proprietaire et n'est pas
-- soumis a ces politiques tant que FORCE ROW LEVEL SECURITY n'est pas active.

BEGIN;

ALTER TABLE public.audit_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.bonuses ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.bot_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.depots ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.difficulties ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.mfa_recovery_codes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.notifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.password_reset_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.performances ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.processed_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.product_targets ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.products ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.sale_lines ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.sales ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.stocks ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.vendors ENABLE ROW LEVEL SECURITY;

-- Le role utilise pour executer cette migration est aussi celui du backend
-- Flask. On lui accorde explicitement l'acces total; anon/authenticated ne
-- figurent dans aucune politique et restent donc bloques par RLS.
DO $fanmilk$
DECLARE
  table_name text;
  protected_tables text[] := ARRAY[
    'audit_logs', 'bonuses', 'bot_sessions', 'depots', 'difficulties',
    'mfa_recovery_codes', 'notifications', 'password_reset_tokens',
    'performances', 'processed_messages', 'product_targets', 'products',
    'sale_lines', 'sales', 'stocks', 'users', 'vendors'
  ];
BEGIN
  FOREACH table_name IN ARRAY protected_tables LOOP
    EXECUTE format(
      'DROP POLICY IF EXISTS fanmilk_backend_full_access ON public.%I',
      table_name
    );
    EXECUTE format(
      'CREATE POLICY fanmilk_backend_full_access ON public.%I '
      'FOR ALL TO %I USING (true) WITH CHECK (true)',
      table_name,
      current_user
    );
  END LOOP;
END
$fanmilk$;

COMMIT;
