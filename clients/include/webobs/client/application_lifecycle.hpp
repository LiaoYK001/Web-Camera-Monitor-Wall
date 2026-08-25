#pragma once

#include <Qt>

namespace webobs::client {

inline bool should_suspend_for_application_state(Qt::ApplicationState state, bool mobile)
{
    return mobile ? state != Qt::ApplicationActive : state == Qt::ApplicationSuspended;
}

}
