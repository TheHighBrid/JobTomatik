package ca.jobtomatik.app;

import android.os.Bundle;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        registerPlugin(NativeRuntimeBootstrapPlugin.class);
        super.onCreate(savedInstanceState);
    }
}
