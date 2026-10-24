package com.resukisu.resukisu.ui.screen.login

import android.os.SystemClock
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.animateContentSize
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.slideInVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.twotone.Lock
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import com.resukisu.resukisu.R
import com.resukisu.resukisu.data.auth.LicenseFailure
import com.resukisu.resukisu.data.auth.LicenseRepository
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

@Composable
fun LicenseGate(content: @Composable () -> Unit) {
    val context = LocalContext.current
    val repository = remember { LicenseRepository(context) }
    // Verification persists in app storage. Returning from a picker or reopening
    // the app must not restart login or discard the current navigation state.
    var authorized by remember { mutableStateOf(repository.hasSession) }
    if (authorized) {
        content()
    } else {
        LoginScreen(repository, onVerified = { authorized = true })
    }
}

private fun loginError(error: Exception): Int = when ((error as? LicenseFailure)?.reason) {
    "not_configured" -> R.string.login_unconfigured
    "invalid_license" -> R.string.login_invalid_license
    "device_bound" -> R.string.login_device_bound
    "invalid_code" -> R.string.login_invalid_code
    "code_expired" -> R.string.login_expired
    "rate_limited" -> R.string.login_rate_limit
    "delivery_failed" -> R.string.login_delivery_error
    "session_expired", "invalid_proof" -> R.string.login_session_expired
    else -> R.string.login_network_error
}

@Composable
private fun LoginScreen(repository: LicenseRepository, onVerified: () -> Unit) {
    var license by remember { mutableStateOf("") }
    var code by remember { mutableStateOf("") }
    var challenge by remember { mutableStateOf<String?>(null) }
    var deadline by remember { mutableLongStateOf(0L) }
    var remaining by remember { mutableIntStateOf(0) }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableIntStateOf(0) }
    val scope = rememberCoroutineScope()
    val reveal = remember { Animatable(0f) }
    LaunchedEffect(Unit) { reveal.animateTo(1f, tween(650)) }
    LaunchedEffect(deadline) {
        while (deadline > 0) {
            remaining = ((deadline - SystemClock.elapsedRealtime() + 999) / 1000).toInt().coerceAtLeast(0)
            if (remaining == 0) break
            delay(200)
        }
    }
    Box(
        Modifier.fillMaxSize().background(Brush.verticalGradient(listOf(
            MaterialTheme.colorScheme.primaryContainer, MaterialTheme.colorScheme.surface)))
            .safeDrawingPadding(), contentAlignment = Alignment.Center
    ) {
        Column(
            Modifier.widthIn(max = 480.dp).verticalScroll(rememberScrollState()).padding(24.dp)
                .graphicsLayer { alpha = reveal.value; translationY = (1 - reveal.value) * 36.dp.toPx() },
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(16.dp)
        ) {
            Icon(Icons.TwoTone.Lock, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
            Text(stringResource(R.string.login_brand), style = MaterialTheme.typography.headlineLarge)
            Text(stringResource(R.string.login_subtitle), style = MaterialTheme.typography.bodyLarge)
            Spacer(Modifier.height(8.dp))
            Card(Modifier.fillMaxWidth().animateContentSize()) {
                Column(Modifier.padding(24.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
                    Text(stringResource(R.string.login_title), style = MaterialTheme.typography.headlineSmall)
                    OutlinedTextField(
                        value = license, onValueChange = { license = it.take(200); challenge = null; deadline = 0; remaining = 0 },
                        label = { Text(stringResource(R.string.login_license)) },
                        singleLine = true, enabled = !busy,
                        visualTransformation = PasswordVisualTransformation(), modifier = Modifier.fillMaxWidth()
                    )
                    AnimatedVisibility(challenge != null, enter = fadeIn() + slideInVertically { it / 3 }) {
                        Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                            OutlinedTextField(
                                value = code, onValueChange = { code = it.filter(Char::isDigit).take(6) },
                                label = { Text(stringResource(R.string.login_code)) },
                                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword),
                                singleLine = true, enabled = !busy && remaining > 0,
                                modifier = Modifier.fillMaxWidth()
                            )
                            Text(if (remaining > 0) stringResource(R.string.login_countdown, remaining)
                                else stringResource(R.string.login_expired), style = MaterialTheme.typography.bodySmall)
                        }
                    }
                    val shownError = if (!repository.configured) R.string.login_unconfigured else error
                    if (shownError != 0) Text(stringResource(shownError), color = MaterialTheme.colorScheme.error)
                    Text(stringResource(R.string.login_privacy), style = MaterialTheme.typography.bodySmall)
                    Button(
                        enabled = repository.configured && !busy && license.isNotBlank() && remaining == 0,
                        modifier = Modifier.fillMaxWidth(),
                        onClick = {
                            busy = true; error = 0
                            scope.launch {
                                try {
                                    // Start the local countdown before the network round trip so it never extends server expiry.
                                    val started = SystemClock.elapsedRealtime()
                                    challenge = null; code = ""
                                    challenge = repository.requestCode(license)
                                    deadline = started + 30_000
                                } catch (e: CancellationException) { throw e
                                } catch (e: Exception) { error = loginError(e)
                                } finally { busy = false }
                            }
                        }
                    ) { Text(stringResource(if (challenge == null) R.string.login_request else R.string.login_resend)) }
                    if (challenge != null) Button(
                        enabled = !busy && remaining > 0 && code.length == 6,
                        modifier = Modifier.fillMaxWidth(),
                        onClick = {
                            val current = challenge ?: return@Button
                            busy = true; error = 0
                            scope.launch {
                                try { repository.verify(current, code); onVerified()
                                } catch (e: CancellationException) { throw e
                                } catch (e: Exception) { error = loginError(e)
                                } finally { busy = false }
                            }
                        }
                    ) { Text(stringResource(R.string.login_verify)) }
                    if (busy) CircularProgressIndicator(Modifier.align(Alignment.CenterHorizontally))
                }
            }
            Text(stringResource(R.string.login_binding), style = MaterialTheme.typography.labelLarge)
        }
    }
}
