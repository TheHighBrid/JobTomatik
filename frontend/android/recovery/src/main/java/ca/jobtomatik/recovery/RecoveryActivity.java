package ca.jobtomatik.recovery;

import android.Manifest;
import android.app.Activity;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.os.Build;
import android.os.Bundle;
import android.view.Gravity;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import java.util.UUID;

public final class RecoveryActivity extends Activity {
    private static final String TERMUX_PERMISSION = "com.termux.permission.RUN_COMMAND";
    private static final int TERMUX_PERMISSION_REQUEST = 7001;

    private static final String TERMUX_PACKAGE = "com.termux";
    private static final String TERMUX_RUN_COMMAND_SERVICE = "com.termux.app.RunCommandService";
    private static final String TERMUX_ACTION_RUN_COMMAND = "com.termux.RUN_COMMAND";
    private static final String TERMUX_EXTRA_COMMAND_PATH = "com.termux.RUN_COMMAND_PATH";
    private static final String TERMUX_EXTRA_ARGUMENTS = "com.termux.RUN_COMMAND_ARGUMENTS";
    private static final String TERMUX_EXTRA_WORKDIR = "com.termux.RUN_COMMAND_WORKDIR";
    private static final String TERMUX_EXTRA_RUNNER = "com.termux.RUN_COMMAND_RUNNER";
    private static final String TERMUX_EXTRA_COMMAND_LABEL = "com.termux.RUN_COMMAND_COMMAND_LABEL";
    private static final String TERMUX_EXTRA_COMMAND_DESCRIPTION = "com.termux.RUN_COMMAND_COMMAND_DESCRIPTION";
    private static final String TERMUX_EXTRA_PENDING_INTENT = "com.termux.RUN_COMMAND_PENDING_INTENT";

    private static final String TERMUX_RESULT_BUNDLE = "result";
    private static final String TERMUX_RESULT_STDOUT = "stdout";
    private static final String TERMUX_RESULT_STDERR = "stderr";
    private static final String TERMUX_RESULT_EXIT_CODE = "exitCode";
    private static final String TERMUX_RESULT_ERR = "err";
    private static final String TERMUX_RESULT_ERRMSG = "errmsg";

    private static final String TERMUX_BIN = "/data/data/com.termux/files/usr/bin/";
    private static final String PROOT_DISTRO = TERMUX_BIN + "proot-distro";
    private static final String JOBTOMATIK = TERMUX_BIN + "jobtomatik";
    private static final String JOBTOMATIK_PILOT = TERMUX_BIN + "jobtomatik-pilot";
    private static final String WORKDIR = "/data/data/com.termux/files/home";
    private static final String BACKEND_PYTHON = "/root/JobTomatik/backend/.venv/bin/python";

    private static final String GLOBAL_EXECUTION_GUARD_CODE =
        "import os,sys\n"
        + "os.chdir('/root/JobTomatik/backend')\n"
        + "sys.path.insert(0,'.')\n"
        + "from app.database import SessionLocal\n"
        + "from app.models.submission_integrity import SubmissionAttempt,SubmissionAttemptStatus\n"
        + "db=SessionLocal()\n"
        + "try:\n"
        + "    count=db.query(SubmissionAttempt.id).filter(SubmissionAttempt.status.in_((SubmissionAttemptStatus.queued.value,SubmissionAttemptStatus.in_progress.value))).count()\n"
        + "    print('JOBTOMATIK_RECOVERY_EXECUTING_ATTEMPTS=%d' % count)\n"
        + "    raise SystemExit(0 if count == 0 else 42)\n"
        + "finally:\n"
        + "    db.close()\n";

    private static final String SUPERVISED_WINDOW_GUARD_CODE =
        "import os,sys\n"
        + "os.chdir('/root/JobTomatik/backend')\n"
        + "sys.path.insert(0,'.')\n"
        + "from app.database import SessionLocal\n"
        + "from app.models.application import Application\n"
        + "from app.models.job import Job\n"
        + "from app.models.submission_integrity import ACTIVE_SUBMISSION_ATTEMPT_STATUSES,SubmissionAttempt,SubmissionAttemptStatus\n"
        + "from app.services.application_state import normalize_state\n"
        + "from app.services.supervised_target_identity import persisted_supervised_target_metadata\n"
        + "db=SessionLocal()\n"
        + "try:\n"
        + "    executing=db.query(SubmissionAttempt.id).filter(SubmissionAttempt.status.in_((SubmissionAttemptStatus.queued.value,SubmissionAttemptStatus.in_progress.value))).count()\n"
        + "    eligible=[]\n"
        + "    for application in db.query(Application).all():\n"
        + "        if normalize_state(application.automation_state) != 'ready_to_apply':\n"
        + "            continue\n"
        + "        job=db.query(Job).filter(Job.id == application.job_id).first()\n"
        + "        if job is None:\n"
        + "            continue\n"
        + "        target=persisted_supervised_target_metadata(job)\n"
        + "        if target.get('verified') is not True or str(target.get('platform') or '').strip().lower() != 'lever' or not str(target.get('posting_id') or '').strip():\n"
        + "            continue\n"
        + "        attempts=db.query(SubmissionAttempt.id).filter(SubmissionAttempt.application_id == application.id,SubmissionAttempt.status.in_(ACTIVE_SUBMISSION_ATTEMPT_STATUSES)).count()\n"
        + "        if attempts:\n"
        + "            continue\n"
        + "        eligible.append(int(application.id))\n"
        + "    print('JOBTOMATIK_RECOVERY_EXECUTING_ATTEMPTS=%d' % executing)\n"
        + "    print('JOBTOMATIK_RECOVERY_ELIGIBLE_LEVER=' + ','.join(str(value) for value in eligible))\n"
        + "    if executing != 0:\n"
        + "        raise SystemExit(42)\n"
        + "    if len(eligible) != 1:\n"
        + "        raise SystemExit(43)\n"
        + "finally:\n"
        + "    db.close()\n";

    private enum Stage {
        IDLE,
        GUARD_UPDATE,
        UPDATE,
        GUARD_ARM,
        ARM,
        DISARM
    }

    private enum PendingAction {
        NONE,
        RECOVERY,
        OPEN_WINDOW,
        CLOSE_WINDOW
    }

    private TextView statusView;
    private TextView detailView;
    private Button repairButton;
    private Button openWindowButton;
    private Button closeWindowButton;
    private Stage stage = Stage.IDLE;
    private PendingAction pendingPermissionAction = PendingAction.NONE;
    private BroadcastReceiver resultReceiver;
    private String armGuardReceipt = "";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        buildUi();
    }

    private void buildUi() {
        ScrollView scroll = new ScrollView(this);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(24), dp(32), dp(24), dp(32));
        root.setGravity(Gravity.CENTER_HORIZONTAL);
        scroll.addView(root);

        TextView title = new TextView(this);
        title.setText("JobTomatik Recovery");
        title.setTextSize(28f);
        title.setTextColor(Color.rgb(15, 23, 42));
        title.setGravity(Gravity.CENTER);
        root.addView(title, fullWidth());

        TextView subtitle = new TextView(this);
        subtitle.setText("Native recovery and supervised-window controls that bypass the JobTomatik WebView. No application is ever submitted or approved from this companion.");
        subtitle.setTextSize(15f);
        subtitle.setTextColor(Color.rgb(71, 85, 105));
        subtitle.setPadding(0, dp(16), 0, dp(24));
        subtitle.setGravity(Gravity.CENTER);
        root.addView(subtitle, fullWidth());

        statusView = new TextView(this);
        statusView.setText("Ready");
        statusView.setTextSize(20f);
        statusView.setTextColor(Color.rgb(15, 23, 42));
        statusView.setGravity(Gravity.CENTER);
        statusView.setPadding(0, dp(8), 0, dp(12));
        root.addView(statusView, fullWidth());

        detailView = new TextView(this);
        detailView.setText("Repair updates the local runtime. Open window first proves there is exactly one verified ready-to-apply Lever candidate and no active or uncertain attempt, then invokes the existing hardened process-bound pilot. Close window restores the ordinary fail-safe runtime.");
        detailView.setTextSize(14f);
        detailView.setTextColor(Color.rgb(71, 85, 105));
        detailView.setGravity(Gravity.CENTER);
        detailView.setPadding(0, 0, 0, dp(24));
        root.addView(detailView, fullWidth());

        repairButton = new Button(this);
        repairButton.setText("Repair JobTomatik runtime");
        repairButton.setAllCaps(false);
        repairButton.setTextSize(16f);
        repairButton.setOnClickListener(v -> requirePermissionThen(PendingAction.RECOVERY));
        root.addView(repairButton, buttonLayout());

        openWindowButton = new Button(this);
        openWindowButton.setText("Open supervised Lever window");
        openWindowButton.setAllCaps(false);
        openWindowButton.setTextSize(16f);
        openWindowButton.setOnClickListener(v -> requirePermissionThen(PendingAction.OPEN_WINDOW));
        LinearLayout.LayoutParams openParams = buttonLayout();
        openParams.topMargin = dp(14);
        root.addView(openWindowButton, openParams);

        closeWindowButton = new Button(this);
        closeWindowButton.setText("Close supervised Lever window");
        closeWindowButton.setAllCaps(false);
        closeWindowButton.setTextSize(16f);
        closeWindowButton.setOnClickListener(v -> requirePermissionThen(PendingAction.CLOSE_WINDOW));
        LinearLayout.LayoutParams closeParams = buttonLayout();
        closeParams.topMargin = dp(14);
        root.addView(closeWindowButton, closeParams);

        TextView footer = new TextView(this);
        footer.setText("Safety boundary: the companion never creates submission approval, never queues work, never changes autopilot/live-submit persisted flags, and accepts no command text from you. The supervised lease expires automatically and final application approval remains in JobTomatik.");
        footer.setTextSize(13f);
        footer.setTextColor(Color.rgb(100, 116, 139));
        footer.setGravity(Gravity.CENTER);
        footer.setPadding(0, dp(24), 0, 0);
        root.addView(footer, fullWidth());

        setContentView(scroll);
    }

    private LinearLayout.LayoutParams fullWidth() {
        return new LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT,
            LinearLayout.LayoutParams.WRAP_CONTENT
        );
    }

    private LinearLayout.LayoutParams buttonLayout() {
        return new LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT,
            dp(56)
        );
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    private void requirePermissionThen(PendingAction action) {
        if (stage != Stage.IDLE) {
            return;
        }
        if (checkSelfPermission(TERMUX_PERMISSION) == PackageManager.PERMISSION_GRANTED) {
            runAction(action);
            return;
        }
        pendingPermissionAction = action;
        statusView.setText("Permission required");
        detailView.setText("Android will ask for permission to run a fixed JobTomatik native command through Termux. Grant it to continue.");
        requestPermissions(new String[] { TERMUX_PERMISSION }, TERMUX_PERMISSION_REQUEST);
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode != TERMUX_PERMISSION_REQUEST) {
            return;
        }
        PendingAction action = pendingPermissionAction;
        pendingPermissionAction = PendingAction.NONE;
        if (grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
            runAction(action);
        } else {
            statusView.setText("Permission not granted");
            detailView.setText("No command was run. Grant the Termux Run Command permission if you want to use this companion.");
        }
    }

    private void runAction(PendingAction action) {
        if (action == PendingAction.RECOVERY) {
            runGlobalGuard();
        } else if (action == PendingAction.OPEN_WINDOW) {
            runSupervisedWindowGuard();
        } else if (action == PendingAction.CLOSE_WINDOW) {
            runDisarm();
        }
    }

    private void runGlobalGuard() {
        setBusy(Stage.GUARD_UPDATE, "Checking submission safety…", "Reading the existing JobTomatik database. Recovery will stop if any submission is queued or in progress.");
        dispatchFixedCommand(
            PROOT_DISTRO,
            new String[] {
                "login",
                "ubuntu",
                "--shared-tmp",
                "--",
                BACKEND_PYTHON,
                "-c",
                GLOBAL_EXECUTION_GUARD_CODE
            },
            "JobTomatik recovery safety guard"
        );
    }

    private void runUpdate() {
        setBusy(Stage.UPDATE, "Updating JobTomatik…", "The local API may disappear for several minutes while the managed Android stack is replaced and verified. Leave this recovery screen open.");
        dispatchFixedCommand(
            JOBTOMATIK,
            new String[] { "update" },
            "JobTomatik fixed runtime update"
        );
    }

    private void runSupervisedWindowGuard() {
        armGuardReceipt = "";
        setBusy(Stage.GUARD_ARM, "Checking Maple/Lever safety…", "The companion will continue only if there is exactly one verified ready-to-apply Lever application, no active or uncertain attempt for that candidate, and nothing queued or executing anywhere.");
        dispatchFixedCommand(
            PROOT_DISTRO,
            new String[] {
                "login",
                "ubuntu",
                "--shared-tmp",
                "--",
                BACKEND_PYTHON,
                "-c",
                SUPERVISED_WINDOW_GUARD_CODE
            },
            "JobTomatik supervised Lever window guard"
        );
    }

    private void runArm() {
        setBusy(Stage.ARM, "Opening supervised Lever window…", "JobTomatik is invoking the existing hardened pilot. The managed stack will restart in fail-safe mode first, then a short process-bound Lever lease will be activated. No submission approval is created.");
        dispatchFixedCommand(
            JOBTOMATIK_PILOT,
            new String[] { "arm" },
            "JobTomatik fixed supervised Lever arm"
        );
    }

    private void runDisarm() {
        setBusy(Stage.DISARM, "Closing supervised Lever window…", "JobTomatik is revoking the process-bound lease and restoring the ordinary fail-safe managed runtime.");
        dispatchFixedCommand(
            JOBTOMATIK_PILOT,
            new String[] { "disarm" },
            "JobTomatik fixed supervised Lever disarm"
        );
    }

    private void setBusy(Stage newStage, String status, String detail) {
        stage = newStage;
        repairButton.setEnabled(false);
        openWindowButton.setEnabled(false);
        closeWindowButton.setEnabled(false);
        statusView.setText(status);
        detailView.setText(detail);
    }

    private void setIdleButtons() {
        stage = Stage.IDLE;
        repairButton.setEnabled(true);
        openWindowButton.setEnabled(true);
        closeWindowButton.setEnabled(true);
    }

    private synchronized void dispatchFixedCommand(String executable, String[] arguments, String description) {
        if (resultReceiver != null) {
            fail("A recovery command is already running.");
            return;
        }

        String resultAction = getPackageName() + ".TERMUX_RESULT." + UUID.randomUUID();
        resultReceiver = new BroadcastReceiver() {
            @Override
            public void onReceive(Context context, Intent intent) {
                handleTermuxResult(intent);
            }
        };

        IntentFilter filter = new IntentFilter(resultAction);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            registerReceiver(resultReceiver, filter, Context.RECEIVER_NOT_EXPORTED);
        } else {
            registerReceiver(resultReceiver, filter);
        }

        Intent callbackIntent = new Intent(resultAction);
        callbackIntent.setPackage(getPackageName());
        int pendingFlags = PendingIntent.FLAG_UPDATE_CURRENT;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            pendingFlags |= PendingIntent.FLAG_MUTABLE;
        }
        PendingIntent callback = PendingIntent.getBroadcast(
            this,
            resultAction.hashCode(),
            callbackIntent,
            pendingFlags
        );

        Intent command = new Intent(TERMUX_ACTION_RUN_COMMAND);
        command.setComponent(new ComponentName(TERMUX_PACKAGE, TERMUX_RUN_COMMAND_SERVICE));
        command.putExtra(TERMUX_EXTRA_COMMAND_PATH, executable);
        command.putExtra(TERMUX_EXTRA_ARGUMENTS, arguments);
        command.putExtra(TERMUX_EXTRA_WORKDIR, WORKDIR);
        command.putExtra(TERMUX_EXTRA_RUNNER, "app-shell");
        command.putExtra(TERMUX_EXTRA_COMMAND_LABEL, "JobTomatik Recovery");
        command.putExtra(TERMUX_EXTRA_COMMAND_DESCRIPTION, description);
        command.putExtra(TERMUX_EXTRA_PENDING_INTENT, callback);

        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                startForegroundService(command);
            } else {
                startService(command);
            }
        } catch (Exception exc) {
            cleanupReceiver();
            fail("Could not start the trusted Termux command: " + safe(exc.getMessage()));
        }
    }

    private synchronized void handleTermuxResult(Intent intent) {
        Bundle result = intent == null ? null : intent.getBundleExtra(TERMUX_RESULT_BUNDLE);
        cleanupReceiver();
        if (result == null) {
            fail("Termux returned no result. Nothing will be retried automatically.");
            return;
        }

        int err = result.getInt(TERMUX_RESULT_ERR, Integer.MIN_VALUE);
        int exitCode = result.getInt(TERMUX_RESULT_EXIT_CODE, -1);
        String errmsg = result.getString(TERMUX_RESULT_ERRMSG, "");
        String stderr = result.getString(TERMUX_RESULT_STDERR, "");
        String stdout = result.getString(TERMUX_RESULT_STDOUT, "");

        if (err != Activity.RESULT_OK) {
            fail(errmsg == null || errmsg.trim().isEmpty()
                ? "Termux rejected the fixed command (internal error " + err + ")."
                : errmsg);
            return;
        }

        if (exitCode != 0) {
            String detail = stderr == null || stderr.trim().isEmpty()
                ? "Fixed command stopped with exit code " + exitCode + "."
                : stderr;
            if (stage == Stage.GUARD_ARM && exitCode == 43) {
                detail = "Supervised window was not opened because the database does not contain exactly one verified ready-to-apply Lever application with no active/uncertain attempt. Nothing was changed.\n\n" + trim(stdout + "\n" + stderr);
            }
            fail(trim(detail));
            return;
        }

        if (stage == Stage.GUARD_UPDATE) {
            runUpdate();
            return;
        }
        if (stage == Stage.UPDATE) {
            setIdleButtons();
            statusView.setText("Recovery completed ✓");
            detailView.setText("JobTomatik update finished successfully. You can now use the native supervised-window controls below without depending on the main app's grey buttons.\n\n" + trim(stdout));
            return;
        }
        if (stage == Stage.GUARD_ARM) {
            armGuardReceipt = trim(stdout);
            runArm();
            return;
        }
        if (stage == Stage.ARM) {
            setIdleButtons();
            statusView.setText("Supervised Lever window opened ✓");
            detailView.setText("The short process-bound Lever lease is active. Persisted submit flags remain OFF and no application approval was issued. Return to JobTomatik and run Fresh Runtime Preflight for the eligible application.\n\n" + armGuardReceipt + "\n\n" + trim(stdout));
            return;
        }
        if (stage == Stage.DISARM) {
            setIdleButtons();
            statusView.setText("Supervised Lever window closed ✓");
            detailView.setText("The temporary lease was revoked and JobTomatik returned to the ordinary fail-safe runtime.\n\n" + trim(stdout));
            return;
        }

        fail("Unexpected recovery state. No command will be replayed.");
    }

    private void fail(String message) {
        setIdleButtons();
        statusView.setText("Stopped safely");
        detailView.setText(message);
    }

    private String trim(String value) {
        String safe = safe(value).trim();
        int limit = 3000;
        return safe.length() <= limit ? safe : safe.substring(safe.length() - limit);
    }

    private String safe(String value) {
        return value == null ? "" : value;
    }

    private synchronized void cleanupReceiver() {
        if (resultReceiver == null) {
            return;
        }
        try {
            unregisterReceiver(resultReceiver);
        } catch (IllegalArgumentException ignored) {
            // Already detached.
        }
        resultReceiver = null;
    }

    @Override
    protected void onDestroy() {
        cleanupReceiver();
        super.onDestroy();
    }
}
