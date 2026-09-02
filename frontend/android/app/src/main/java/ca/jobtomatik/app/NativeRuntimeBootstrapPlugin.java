package ca.jobtomatik.app;

import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.os.Build;
import android.os.Bundle;

import androidx.core.content.ContextCompat;

import com.getcapacitor.JSObject;
import com.getcapacitor.PermissionState;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import com.getcapacitor.annotation.Permission;
import com.getcapacitor.annotation.PermissionCallback;

import java.util.UUID;

@CapacitorPlugin(
    name = "NativeRuntimeBootstrap",
    permissions = {
        @Permission(
            strings = { NativeRuntimeBootstrapPlugin.TERMUX_RUN_COMMAND_PERMISSION },
            alias = NativeRuntimeBootstrapPlugin.TERMUX_PERMISSION_ALIAS
        )
    }
)
public class NativeRuntimeBootstrapPlugin extends Plugin {

    static final String TERMUX_RUN_COMMAND_PERMISSION = "com.termux.permission.RUN_COMMAND";
    static final String TERMUX_PERMISSION_ALIAS = "termuxRunCommand";

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
    private static final String JOBTOMATIK_COMMAND = TERMUX_BIN + "jobtomatik";
    private static final String PILOT_CONTROLLER_MANAGER = TERMUX_BIN + "jobtomatik-pilot-controller-manager";
    private static final String PROOT_DISTRO = TERMUX_BIN + "proot-distro";
    private static final String JOBTOMATIK_WORKDIR = "/data/data/com.termux/files/home";
    private static final String BACKEND_ROOT = "/root/JobTomatik/backend";
    private static final String BACKEND_PYTHON = BACKEND_ROOT + "/.venv/bin/python";
    private static final String GLOBAL_EXECUTION_GUARD_CODE =
        "import os,sys;"
        + "os.chdir('/root/JobTomatik/backend');"
        + "sys.path.insert(0,'.');"
        + "from app.database import SessionLocal;"
        + "from app.models.submission_integrity import SubmissionAttempt,SubmissionAttemptStatus;"
        + "db=SessionLocal();"
        + "count=db.query(SubmissionAttempt.id).filter(SubmissionAttempt.status.in_((SubmissionAttemptStatus.queued.value,SubmissionAttemptStatus.in_progress.value))).count();"
        + "db.close();"
        + "print('JOBTOMATIK_BOOTSTRAP_EXECUTING_ATTEMPTS=%d' % count);"
        + "raise SystemExit(0 if count == 0 else 42)";

    private BroadcastReceiver resultReceiver;

    @PluginMethod
    public void quiesceController(PluginCall call) {
        if (requestPermissionIfNeeded(call, "quiescePermissionCallback")) {
            return;
        }
        dispatchControllerStop(call);
    }

    @PermissionCallback
    private void quiescePermissionCallback(PluginCall call) {
        if (!permissionGranted(call)) {
            return;
        }
        dispatchControllerStop(call);
    }

    @PluginMethod
    public void assertNoExecutingSubmissions(PluginCall call) {
        if (requestPermissionIfNeeded(call, "executionGuardPermissionCallback")) {
            return;
        }
        dispatchGlobalExecutionGuard(call);
    }

    @PermissionCallback
    private void executionGuardPermissionCallback(PluginCall call) {
        if (!permissionGranted(call)) {
            return;
        }
        dispatchGlobalExecutionGuard(call);
    }

    @PluginMethod
    public void restoreController(PluginCall call) {
        if (requestPermissionIfNeeded(call, "restorePermissionCallback")) {
            return;
        }
        dispatchControllerStart(call);
    }

    @PermissionCallback
    private void restorePermissionCallback(PluginCall call) {
        if (!permissionGranted(call)) {
            return;
        }
        dispatchControllerStart(call);
    }

    @PluginMethod
    public void updateRuntime(PluginCall call) {
        if (requestPermissionIfNeeded(call, "updatePermissionCallback")) {
            return;
        }
        dispatchRuntimeUpdate(call);
    }

    @PermissionCallback
    private void updatePermissionCallback(PluginCall call) {
        if (!permissionGranted(call)) {
            return;
        }
        dispatchRuntimeUpdate(call);
    }

    private boolean requestPermissionIfNeeded(PluginCall call, String callbackName) {
        if (getPermissionState(TERMUX_PERMISSION_ALIAS) == PermissionState.GRANTED) {
            return false;
        }
        requestPermissionForAlias(TERMUX_PERMISSION_ALIAS, call, callbackName);
        return true;
    }

    private boolean permissionGranted(PluginCall call) {
        if (getPermissionState(TERMUX_PERMISSION_ALIAS) == PermissionState.GRANTED) {
            return true;
        }
        call.reject(
            "JobTomatik needs the Termux Run Command permission for the one-time native runtime bootstrap."
        );
        return false;
    }

    private void dispatchControllerStop(PluginCall call) {
        dispatchFixedCommand(
            call,
            PILOT_CONTROLLER_MANAGER,
            new String[] { "stop" },
            "pilot-controller-stop",
            "Quiesce JobTomatik native pilot control before the one-time runtime bootstrap."
        );
    }

    private void dispatchGlobalExecutionGuard(PluginCall call) {
        dispatchFixedCommand(
            call,
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
            "global-submission-execution-guard",
            "Read JobTomatik's existing database directly and fail closed if any queued or in-progress submission attempt exists."
        );
    }

    private void dispatchControllerStart(PluginCall call) {
        dispatchFixedCommand(
            call,
            PILOT_CONTROLLER_MANAGER,
            new String[] { "start" },
            "pilot-controller-start",
            "Restore JobTomatik native pilot control after an aborted bootstrap."
        );
    }

    private void dispatchRuntimeUpdate(PluginCall call) {
        dispatchFixedCommand(
            call,
            JOBTOMATIK_COMMAND,
            new String[] { "update" },
            "termux-fixed-jobtomatik-update",
            "Run the fixed JobTomatik native updater. No caller-supplied command or arguments are accepted."
        );
    }

    private synchronized void dispatchFixedCommand(
        PluginCall call,
        String executable,
        String[] arguments,
        String mode,
        String description
    ) {
        if (resultReceiver != null) {
            call.reject("A native JobTomatik runtime bootstrap command is already in progress.");
            return;
        }

        final Context context = getContext();
        final String resultAction = context.getPackageName()
            + ".NATIVE_RUNTIME_BOOTSTRAP_RESULT."
            + UUID.randomUUID();

        resultReceiver = new BroadcastReceiver() {
            @Override
            public void onReceive(Context receiverContext, Intent intent) {
                handleResult(call, intent, mode);
            }
        };

        ContextCompat.registerReceiver(
            context,
            resultReceiver,
            new IntentFilter(resultAction),
            ContextCompat.RECEIVER_NOT_EXPORTED
        );

        Intent callbackIntent = new Intent(resultAction);
        callbackIntent.setPackage(context.getPackageName());
        int pendingIntentFlags = PendingIntent.FLAG_UPDATE_CURRENT;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            // Termux must be able to attach its result bundle to this callback.
            pendingIntentFlags |= PendingIntent.FLAG_MUTABLE;
        }
        PendingIntent resultPendingIntent = PendingIntent.getBroadcast(
            context,
            resultAction.hashCode(),
            callbackIntent,
            pendingIntentFlags
        );

        Intent commandIntent = new Intent(TERMUX_ACTION_RUN_COMMAND);
        commandIntent.setClassName(TERMUX_PACKAGE, TERMUX_RUN_COMMAND_SERVICE);
        commandIntent.putExtra(TERMUX_EXTRA_COMMAND_PATH, executable);
        commandIntent.putExtra(TERMUX_EXTRA_ARGUMENTS, arguments);
        commandIntent.putExtra(TERMUX_EXTRA_WORKDIR, JOBTOMATIK_WORKDIR);
        commandIntent.putExtra(TERMUX_EXTRA_RUNNER, "app-shell");
        commandIntent.putExtra(TERMUX_EXTRA_COMMAND_LABEL, "JobTomatik verified runtime bootstrap");
        commandIntent.putExtra(TERMUX_EXTRA_COMMAND_DESCRIPTION, description);
        commandIntent.putExtra(TERMUX_EXTRA_PENDING_INTENT, resultPendingIntent);

        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(commandIntent);
            } else {
                context.startService(commandIntent);
            }
        } catch (Exception exc) {
            cleanupReceiver();
            call.reject(
                "Unable to start the trusted Termux JobTomatik command: " + exc.getMessage()
            );
        }
    }

    private synchronized void handleResult(PluginCall call, Intent intent, String mode) {
        Bundle result = intent == null ? null : intent.getBundleExtra(TERMUX_RESULT_BUNDLE);
        cleanupReceiver();

        if (result == null) {
            call.reject("Termux returned no native bootstrap result.");
            return;
        }

        int err = result.getInt(TERMUX_RESULT_ERR, Integer.MIN_VALUE);
        int exitCode = result.getInt(TERMUX_RESULT_EXIT_CODE, -1);
        String errmsg = result.getString(TERMUX_RESULT_ERRMSG, "");
        String stdout = result.getString(TERMUX_RESULT_STDOUT, "");
        String stderr = result.getString(TERMUX_RESULT_STDERR, "");

        // Termux follows Android's Activity result contract: Activity.RESULT_OK (-1)
        // means no internal Termux error. Zero is not success here.
        if (err != android.app.Activity.RESULT_OK) {
            String detail = errmsg == null || errmsg.trim().isEmpty()
                ? "Termux rejected the native runtime bootstrap command (internal error " + err + ")."
                : errmsg;
            call.reject(detail);
            return;
        }

        if (exitCode != 0) {
            String detail = stderr == null || stderr.trim().isEmpty()
                ? "JobTomatik native bootstrap command failed with exit code " + exitCode + "."
                : stderr;
            call.reject(detail);
            return;
        }

        JSObject response = new JSObject();
        response.put("accepted", true);
        response.put("completed", true);
        response.put("exitCode", exitCode);
        response.put("mode", mode);
        response.put("stdout", truncate(stdout));
        call.resolve(response);
    }

    private String truncate(String value) {
        if (value == null) {
            return "";
        }
        int limit = 2000;
        return value.length() <= limit ? value : value.substring(value.length() - limit);
    }

    private synchronized void cleanupReceiver() {
        if (resultReceiver == null) {
            return;
        }
        try {
            getContext().unregisterReceiver(resultReceiver);
        } catch (IllegalArgumentException ignored) {
            // Receiver was already detached.
        }
        resultReceiver = null;
    }

    @Override
    protected void handleOnDestroy() {
        cleanupReceiver();
        super.handleOnDestroy();
    }
}
