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
import android.view.View;
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
    private static final String WORKDIR = "/data/data/com.termux/files/home";
    private static final String BACKEND_PYTHON = "/root/JobTomatik/backend/.venv/bin/python";

    private static final String GLOBAL_EXECUTION_GUARD_CODE =
        "import os,sys;"
        + "os.chdir('/root/JobTomatik/backend');"
        + "sys.path.insert(0,'.');"
        + "from app.database import SessionLocal;"
        + "from app.models.submission_integrity import SubmissionAttempt,SubmissionAttemptStatus;"
        + "db=SessionLocal();"
        + "count=db.query(SubmissionAttempt.id).filter(SubmissionAttempt.status.in_((SubmissionAttemptStatus.queued.value,SubmissionAttemptStatus.in_progress.value))).count();"
        + "db.close();"
        + "print('JOBTOMATIK_RECOVERY_EXECUTING_ATTEMPTS=%d' % count);"
        + "raise SystemExit(0 if count == 0 else 42)";

    private enum Stage {
        IDLE,
        GUARD,
        UPDATE
    }

    private TextView statusView;
    private TextView detailView;
    private Button repairButton;
    private Stage stage = Stage.IDLE;
    private BroadcastReceiver resultReceiver;

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
        subtitle.setText("One-time Android runtime recovery. This app never submits an application, never changes approval state, and accepts no command text from you.");
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
        detailView.setText("Step 1 checks the existing JobTomatik database and stops if any submission is queued or in progress. Step 2 runs the fixed JobTomatik updater through Termux.");
        detailView.setTextSize(14f);
        detailView.setTextColor(Color.rgb(71, 85, 105));
        detailView.setGravity(Gravity.CENTER);
        detailView.setPadding(0, 0, 0, dp(24));
        root.addView(detailView, fullWidth());

        repairButton = new Button(this);
        repairButton.setText("Repair JobTomatik runtime");
        repairButton.setAllCaps(false);
        repairButton.setTextSize(16f);
        repairButton.setOnClickListener(v -> beginRecovery());
        root.addView(repairButton, new LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT,
            dp(56)
        ));

        TextView footer = new TextView(this);
        footer.setText("Safe boundary: Fullscript 246 remains quarantined. Maple 247 is not submitted or approved by this recovery action.");
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

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    private void beginRecovery() {
        if (stage != Stage.IDLE) {
            return;
        }
        if (checkSelfPermission(TERMUX_PERMISSION) != PackageManager.PERMISSION_GRANTED) {
            statusView.setText("Permission required");
            detailView.setText("Android will ask for permission to run the fixed JobTomatik maintenance command in Termux. Grant it to continue.");
            requestPermissions(new String[] { TERMUX_PERMISSION }, TERMUX_PERMISSION_REQUEST);
            return;
        }
        runGlobalGuard();
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode != TERMUX_PERMISSION_REQUEST) {
            return;
        }
        if (grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
            runGlobalGuard();
        } else {
            statusView.setText("Permission not granted");
            detailView.setText("No command was run. Grant the Termux Run Command permission if you want to use this recovery app.");
        }
    }

    private void runGlobalGuard() {
        setBusy(Stage.GUARD, "Checking submission safety…", "Reading the existing JobTomatik database. Recovery will stop if any submission is queued or in progress.");
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

    private void setBusy(Stage newStage, String status, String detail) {
        stage = newStage;
        repairButton.setEnabled(false);
        statusView.setText(status);
        detailView.setText(detail);
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
            fail("Could not start the trusted Termux recovery command: " + safe(exc.getMessage()));
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
                ? "Termux rejected the recovery command (internal error " + err + ")."
                : errmsg);
            return;
        }

        if (exitCode != 0) {
            String detail = stderr == null || stderr.trim().isEmpty()
                ? "Recovery command stopped with exit code " + exitCode + "."
                : stderr;
            fail(trim(detail));
            return;
        }

        if (stage == Stage.GUARD) {
            runUpdate();
            return;
        }
        if (stage == Stage.UPDATE) {
            stage = Stage.IDLE;
            statusView.setText("Recovery completed ✓");
            detailView.setText("JobTomatik update finished successfully. Return to the main JobTomatik app, sign in again if requested, and open Current Lever.\n\n" + trim(stdout));
            repairButton.setText("Recovery completed");
            repairButton.setEnabled(false);
            return;
        }

        fail("Unexpected recovery state. No command will be replayed.");
    }

    private void fail(String message) {
        stage = Stage.IDLE;
        statusView.setText("Recovery stopped safely");
        detailView.setText(message);
        repairButton.setText("Try recovery again");
        repairButton.setEnabled(true);
    }

    private String trim(String value) {
        String safe = safe(value).trim();
        int limit = 2500;
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
