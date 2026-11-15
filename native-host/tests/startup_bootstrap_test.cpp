// Executable callback-order regression, not a Qt/OBS product acceptance test.
#include "startup_bootstrap.hpp"
#include "native_ui_gate.hpp"

#include <cstdio>
#include <cstdlib>
#include <stdexcept>
#include <string>
#include <vector>

using namespace webobs::native_host;

static void require(bool condition, const char *message)
{
	if (!condition) {
		std::fprintf(stderr, "startup bootstrap test failed: %s\n", message);
		std::exit(1);
	}
}

int main()
{
	for (bool requested : {false, true}) {
		for (bool isolated : {false, true}) {
			std::vector<std::string> effects;
			const auto result = run_startup_bootstrap({requested, isolated}, [&] {
				effects.push_back("backup");
				effects.push_back("config-read");
				effects.push_back("video-reset");
				effects.push_back("source-create");
				effects.push_back("wall-select");
				effects.push_back("ownership-write");
			});
			if (requested && isolated) {
				require(result == StartupBootstrapStatus::diagnostic_completed, "explicit isolated diagnostic runs");
				require(effects == std::vector<std::string>{"backup", "config-read", "video-reset", "source-create", "wall-select", "ownership-write"},
					"exactly one callback preserves diagnostic operation order");
			} else {
				require(result == StartupBootstrapStatus::refused, "incomplete diagnostic context refuses");
				require(effects.empty(), "refusal precedes ALL plugin startup effects");
			}
		}
	}
	require(run_startup_bootstrap({true, true}, {}) == StartupBootstrapStatus::refused,
		"empty callback refuses without effects");
	int calls = 0;
	require(run_startup_bootstrap({true, true}, [&] { ++calls; throw std::runtime_error("synthetic"); }) ==
		StartupBootstrapStatus::diagnostic_failed, "throwing diagnostic fails, not authorized");
	require(calls == 1, "failed diagnostic not retried");
	for (int mask = 0; mask != 16; ++mask) {
		UiAuthorizationState state;
		state.operator_session_bound = (mask & 1) != 0;
		state.decision_ready = (mask & 2) != 0;
		state.plan_ready = (mask & 4) != 0;
		state.backup_captured = (mask & 8) != 0;
		require(evaluate_ui_action(UiActionKind::auto_bootstrap_on_load, state) == UiGateStatus::refused_no_session,
			"all operator-state combinations still refuse automatic bootstrap");
	}
	std::puts("startup bootstrap callback-order tests passed");
}
