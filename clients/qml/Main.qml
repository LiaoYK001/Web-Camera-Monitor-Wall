import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: window
    width: clientController.androidPlatform ? 430 : 1440
    height: clientController.androidPlatform ? 820 : 900
    visible: true
    color: "#0b0f15"
    title: "WebObs Native — True Direct"
    property bool monitorFullscreen: false
    property bool studioMode: false
    property bool compactMonitor: clientController.androidPlatform || width < 900
    onStudioModeChanged: clientController.setStudioActive(studioMode)

    function enterMonitorFullscreen() {
        monitorFullscreen = true
        studioMode = false
        visibility = Window.FullScreen
        clientController.setMonitoringFullscreen(true)
    }
    function leaveMonitorFullscreen() {
        monitorFullscreen = false
        visibility = Window.Windowed
        clientController.setMonitoringFullscreen(false)
    }
    onVisibilityChanged: {
        if (visibility !== Window.FullScreen && monitorFullscreen)
            leaveMonitorFullscreen()
    }

    Connections {
        target: clientController
        function onUserError(message) {
            errorBanner.color = "#9c2f37"
            errorBanner.text = message
            errorBanner.visible = true
        }
        function onOperationCompleted(message) {
            errorBanner.color = "#176b45"
            errorBanner.text = message
            errorBanner.visible = true
        }
    }

    header: ToolBar {
        visible: !window.monitorFullscreen
        RowLayout {
            anchors.fill: parent
            Label { text: "WebObs Native"; font.bold: true; Layout.leftMargin: 12 }
            ToolButton {
                text: "Monitor"
                checked: !window.studioMode
                checkable: true
                onClicked: window.studioMode = false
            }
            ToolButton {
                text: "Studio"
                visible: !clientController.androidPlatform
                checked: window.studioMode
                checkable: true
                onClicked: window.studioMode = true
            }
            Item { Layout.fillWidth: true }
            Label {
                visible: !window.compactMonitor
                text: clientController.gridStreams.count + " grid + " +
                      clientController.focusStreams.count + " focus"
            }
            Label {
                visible: !window.compactMonitor
                text: clientController.liveTopology + " / archive: " + clientController.archiveTopology
            }
            Button { text: "Fullscreen"; onClicked: window.enterMonitorFullscreen() }
        }
    }

    Rectangle {
        id: errorBanner
        visible: false
        z: 100
        anchors.top: parent.top
        anchors.horizontalCenter: parent.horizontalCenter
        width: Math.min(parent.width - 32, 760)
        height: Math.max(48, errorText.implicitHeight + 20)
        radius: 6
        color: "#9c2f37"
        property alias text: errorText.text
        Text {
            id: errorText
            anchors.centerIn: parent
            width: parent.width - 24
            color: "white"
            wrapMode: Text.Wrap
            horizontalAlignment: Text.AlignHCenter
        }
        TapHandler { onTapped: errorBanner.visible = false }
    }

    StackLayout {
        anchors.fill: parent
        currentIndex: clientController.state === "unpaired" ||
                      clientController.state === "enrolling" ||
                      clientController.state === "pending-approval" ? 0 : 1

        Pane {
            ColumnLayout {
                anchors.centerIn: parent
                width: Math.min(520, parent.width - 40)
                spacing: 12
                Label { text: "Pair this local client"; font.pixelSize: 28; font.bold: true }
                TextField { id: server; placeholderText: "https://webobs.example:8443"; Layout.fillWidth: true }
                TextField {
                    id: deviceName
                    placeholderText: "Device name"
                    text: Qt.platform.os + " monitor"
                    Layout.fillWidth: true
                }
                Label { text: "Secure storage: " + clientController.storageBackend }
                Label {
                    visible: clientController.temporaryIdentity
                    color: "#ffbf69"
                    text: "Secure storage unavailable: this session will not survive an app restart."
                    wrapMode: Text.Wrap
                }
                Button {
                    text: "Request pairing code"
                    enabled: server.text.length > 0 && deviceName.text.length > 0
                    onClicked: {
                        clientController.serverUrl = server.text
                        clientController.enroll(deviceName.text)
                    }
                }
                Label {
                    visible: clientController.pairingCode.length === 8
                    text: clientController.pairingCode
                    font.pixelSize: 42
                    font.letterSpacing: 5
                    Layout.alignment: Qt.AlignHCenter
                }
                Label { text: clientController.statusText; wrapMode: Text.Wrap; Layout.fillWidth: true }
            }
        }

        Item {
            RowLayout {
                anchors.fill: parent
                spacing: 0

                Pane {
                    visible: !window.monitorFullscreen && !window.compactMonitor
                    Layout.preferredWidth: 310
                    Layout.fillHeight: true
                    ColumnLayout {
                        anchors.fill: parent
                        Label { text: "Local monitor"; font.bold: true; font.pixelSize: 18 }
                        RowLayout {
                            Repeater {
                                model: [1, 4, 9, 16]
                                Button {
                                    required property int modelData
                                    text: modelData.toString()
                                    checkable: true
                                    checked: clientController.gridCapacity === modelData
                                    enabled: modelData !== 16 || clientController.grid16Available
                                    onClicked: clientController.activateGrid(modelData)
                                }
                            }
                        }
                        Label {
                            text: "Substreams stay in the grid. Select a camera to open an independent main-stream focus."
                            wrapMode: Text.Wrap
                            Layout.fillWidth: true
                            color: "#aab7c8"
                        }
                        ListView {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            clip: true
                            model: clientController.cameras
                            delegate: ItemDelegate {
                                required property var modelData
                                width: ListView.view.width
                                text: modelData.name
                                onClicked: clientController.focusCamera(modelData.cameraId)
                            }
                        }
                        Label { text: "Last fallback: " + clientController.fallbackReason; wrapMode: Text.Wrap }
                        TextField { id: remuxInput; placeholderText: "Absolute recorded .mkv path"; Layout.fillWidth: true }
                        Button {
                            visible: !clientController.androidPlatform
                            text: "Export MKV to MP4"
                            enabled: remuxInput.text.length > 0
                            onClicked: clientController.exportMkvToMp4(
                                remuxInput.text, clientController.suggestedCapturePath("mp4"))
                        }
                        Button {
                            visible: clientController.androidPlatform
                            text: "Export last capture"
                            enabled: clientController.lastCapturePath.length > 0
                            onClicked: clientController.exportLastCapture()
                        }
                        Button { text: "Stop all local media"; onClicked: clientController.stopAll() }
                    }
                }

                StackLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    currentIndex: window.studioMode ? 1 : 0

                    Item {
                        id: monitorSurface
                        property int columns: clientController.gridCapacity === 1 ? 1 :
                                              clientController.gridCapacity === 4 ? 2 :
                                              clientController.gridCapacity === 9 ? 3 : 4
                        Rectangle { anchors.fill: parent; color: "#05070a" }
                        GridView {
                            id: streamGrid
                            anchors.fill: parent
                            anchors.margins: 4
                            model: clientController.gridStreams
                            cellWidth: width / monitorSurface.columns
                            cellHeight: height / monitorSurface.columns
                            interactive: false
                            delegate: MonitorTile {
                                required property string sessionId
                                required property string cameraId
                                required property string title
                                required property var media
                                required property string topology
                                required property string archiveTopology
                                required property string fallbackReason
                                required property int reconnectCount
                                width: streamGrid.cellWidth
                                height: streamGrid.cellHeight
                                streamSessionId: sessionId
                                streamCameraId: cameraId
                                streamMedia: media
                                streamTopology: topology
                                streamArchiveTopology: archiveTopology
                                streamFallbackReason: fallbackReason
                                streamReconnectCount: reconnectCount
                                focused: false
                                displayTitle: title
                            }
                        }
                        Label {
                            anchors.centerIn: parent
                            visible: clientController.gridStreams.count === 0
                            color: "#8fa0b5"
                            text: "Choose 1 / 4 / 9 / 16 to start local substreams"
                        }
                        Repeater {
                            model: clientController.focusStreams
                            delegate: MonitorTile {
                                required property string sessionId
                                required property string cameraId
                                required property string title
                                required property var media
                                required property string topology
                                required property string archiveTopology
                                required property string fallbackReason
                                required property int reconnectCount
                                z: 20
                                anchors.fill: monitorSurface
                                anchors.margins: window.monitorFullscreen ? 0 : 20
                                streamSessionId: sessionId
                                streamCameraId: cameraId
                                streamMedia: media
                                streamTopology: topology
                                streamArchiveTopology: archiveTopology
                                streamFallbackReason: fallbackReason
                                streamReconnectCount: reconnectCount
                                focused: true
                                displayTitle: title + " — main"
                            }
                        }
                        Button {
                            visible: window.monitorFullscreen
                            z: 30
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.margins: 16
                            text: "Exit fullscreen"
                            onClicked: window.leaveMonitorFullscreen()
                        }
                        Pane {
                            visible: window.compactMonitor && !window.monitorFullscreen
                            z: 25
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.bottom: parent.bottom
                            padding: 8
                            background: Rectangle { color: "#dd111821"; radius: 8 }
                            ColumnLayout {
                                width: parent.width
                                RowLayout {
                                    Layout.fillWidth: true
                                    Repeater {
                                        model: [1, 4, 9, 16]
                                        Button {
                                            required property int modelData
                                            text: modelData.toString()
                                            checkable: true
                                            checked: clientController.gridCapacity === modelData
                                            enabled: modelData !== 16 || clientController.grid16Available
                                            onClicked: clientController.activateGrid(modelData)
                                        }
                                    }
                                    Button { text: "Full"; onClicked: window.enterMonitorFullscreen() }
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    ComboBox {
                                        id: mobileCamera
                                        Layout.fillWidth: true
                                        textRole: "name"
                                        valueRole: "cameraId"
                                        model: clientController.cameras
                                    }
                                    Button {
                                        text: "Focus"
                                        enabled: mobileCamera.currentValue !== undefined
                                        onClicked: clientController.focusCamera(mobileCamera.currentValue)
                                    }
                                    Button {
                                        text: "Export"
                                        enabled: clientController.lastCapturePath.length > 0
                                        onClicked: clientController.exportLastCapture()
                                    }
                                }
                                Label {
                                    Layout.fillWidth: true
                                    elide: Text.ElideRight
                                    color: clientController.thermalStatus === "severe" ? "#ff8d8d" : "#aab7c8"
                                    text: "Network " + clientController.networkStatus +
                                          " · MediaCodec " + clientController.hardwareDecoderInstances +
                                          " · Thermal " + clientController.thermalStatus +
                                          " · Wake " + (clientController.wakeLockActive ? "on" : "off")
                                }
                            }
                        }
                    }

                    Item {
                        visible: !clientController.androidPlatform
                        RowLayout {
                            anchors.fill: parent
                            spacing: 4
                            Pane {
                                Layout.preferredWidth: 210
                                Layout.fillHeight: true
                                ColumnLayout {
                                    anchors.fill: parent
                                    Label { text: "Scenes"; font.bold: true }
                                    ListView {
                                        Layout.fillWidth: true
                                        Layout.fillHeight: true
                                        model: clientController.studio.scenes
                                        delegate: ItemDelegate {
                                            required property var modelData
                                            width: ListView.view.width
                                            text: modelData.name +
                                                  (modelData.sceneId === clientController.studio.programSceneId ? "  [P]" : "") +
                                                  (modelData.sceneId === clientController.studio.previewSceneId ? "  [V]" : "")
                                            highlighted: modelData.sceneId === clientController.studio.previewSceneId
                                            onClicked: clientController.studio.selectPreview(modelData.sceneId)
                                        }
                                    }
                                    TextField { id: newSceneName; placeholderText: "New scene"; Layout.fillWidth: true }
                                    Button {
                                        text: "Add scene"
                                        enabled: newSceneName.text.length > 0
                                        onClicked: {
                                            if (clientController.studio.addScene(newSceneName.text))
                                                newSceneName.clear()
                                        }
                                    }
                                    Button {
                                        text: "Remove Preview"
                                        onClicked: clientController.studio.removeScene(clientController.studio.previewSceneId)
                                    }
                                    Button {
                                        text: "Save local collection"
                                        onClicked: clientController.studio.saveLocal(
                                            clientController.suggestedCapturePath("json"))
                                    }
                                }
                            }
                            ColumnLayout {
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                RowLayout {
                                    Layout.fillWidth: true
                                    Label { text: "Local Studio · same Scene v5 contract"; font.bold: true }
                                    Item { Layout.fillWidth: true }
                                    Button { text: "Cut"; onClicked: clientController.studio.take("cut", 0) }
                                    SpinBox { id: fadeDuration; from: 50; to: 2000; value: 350; editable: true }
                                    Button { text: "Fade"; onClicked: clientController.studio.take("fade", fadeDuration.value) }
                                }
                                SplitView {
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    orientation: Qt.Vertical
                                    StudioCanvas {
                                        id: programCanvas
                                        SplitView.fillWidth: true
                                        SplitView.preferredHeight: parent.height / 2
                                        sceneModel: clientController.studio.program
                                        editMode: false
                                        busLabel: "Program"
                                        programBus: true
                                    }
                                    StudioCanvas {
                                        id: previewCanvas
                                        SplitView.fillWidth: true
                                        SplitView.fillHeight: true
                                        sceneModel: clientController.studio.preview
                                        editMode: true
                                        busLabel: "Preview"
                                        programBus: false
                                    }
                                }
                                Connections {
                                    target: clientController.studio
                                    function onTransitionStarted(kind, durationMs) {
                                        if (kind === "fade") {
                                            programCanvas.opacity = 0
                                            fadeAnimation.duration = durationMs
                                            fadeAnimation.restart()
                                        } else {
                                            programCanvas.opacity = 1
                                        }
                                    }
                                }
                                NumberAnimation { id: fadeAnimation; target: programCanvas; property: "opacity"; to: 1 }
                            }
                            Pane {
                                Layout.preferredWidth: 250
                                Layout.fillHeight: true
                                ScrollView {
                                    anchors.fill: parent
                                    ColumnLayout {
                                        width: 224
                                        Label { text: "Sources"; font.bold: true }
                                        Button {
                                            text: "Add first camera"
                                            enabled: clientController.cameras.length > 0
                                            onClicked: {
                                                const camera = clientController.cameras[0]
                                                if (camera.profiles.length > 0)
                                                    clientController.studio.preview.addCamera(
                                                        camera.cameraId, camera.profiles[0].id, camera.name)
                                            }
                                        }
                                        TextField { id: textSource; placeholderText: "Text overlay"; Layout.fillWidth: true }
                                        Button { text: "Add text"; onClicked: clientController.studio.preview.addText(textSource.text) }
                                        TextField { id: colorSource; text: "#203040"; Layout.fillWidth: true }
                                        Button { text: "Add color"; onClicked: clientController.studio.preview.addColor(colorSource.text) }
                                        TextField { id: imageSource; placeholderText: "Absolute image path"; Layout.fillWidth: true }
                                        Button { text: "Add image"; onClicked: clientController.studio.preview.addImage(imageSource.text) }
                                        Button {
                                            text: "Add nested scene"
                                            enabled: clientController.studio.scenes.length > 1
                                            onClicked: {
                                                for (let candidate of clientController.studio.scenes) {
                                                    if (candidate.sceneId !== clientController.studio.previewSceneId) {
                                                        clientController.studio.preview.addNested(candidate.sceneId, candidate.name)
                                                        break
                                                    }
                                                }
                                            }
                                        }
                                        MenuSeparator { Layout.fillWidth: true }
                                        Label { text: "Selected item " + previewCanvas.selectedRow; font.bold: true }
                                        RowLayout {
                                            Button { text: "Show"; onClicked: clientController.studio.preview.setItemVisible(previewCanvas.selectedRow, true) }
                                            Button { text: "Hide"; onClicked: clientController.studio.preview.setItemVisible(previewCanvas.selectedRow, false) }
                                            Button { text: "Lock"; onClicked: clientController.studio.preview.setItemLocked(previewCanvas.selectedRow, true) }
                                            Button { text: "Unlock"; onClicked: clientController.studio.preview.setItemLocked(previewCanvas.selectedRow, false) }
                                        }
                                        TextField { id: groupId; placeholderText: "Group ID"; Layout.fillWidth: true }
                                        Button { text: "Set group"; onClicked: clientController.studio.preview.setItemGroup(previewCanvas.selectedRow, groupId.text) }
                                        Label { text: "Rotation" }
                                        SpinBox {
                                            from: -360; to: 360; value: 0; editable: true
                                            onValueModified: clientController.studio.preview.setItemRotation(previewCanvas.selectedRow, value)
                                        }
                                        Label { text: "Opacity" }
                                        Slider {
                                            from: 0; to: 1; value: 1; stepSize: 0.05; Layout.fillWidth: true
                                            onMoved: clientController.studio.preview.setItemOpacity(previewCanvas.selectedRow, value)
                                        }
                                        ComboBox {
                                            model: ["contain", "cover", "stretch"]
                                            onActivated: clientController.studio.preview.setItemScaleMode(previewCanvas.selectedRow, currentText)
                                        }
                                        Label { text: "Basic source filters"; font.bold: true }
                                        Label { text: "Brightness" }
                                        Slider {
                                            id: filterBrightness
                                            from: -1; to: 1; value: 0; stepSize: 0.05
                                            Layout.fillWidth: true
                                        }
                                        Label { text: "Filter opacity" }
                                        Slider {
                                            id: filterOpacity
                                            from: 0; to: 1; value: 1; stepSize: 0.05
                                            Layout.fillWidth: true
                                        }
                                        TextField {
                                            id: filterScale
                                            placeholderText: "Scale, e.g. 640x360"
                                            Layout.fillWidth: true
                                        }
                                        TextField {
                                            id: filterMask
                                            placeholderText: "Optional /assets/... or /recordings/... mask"
                                            Layout.fillWidth: true
                                        }
                                        Button {
                                            text: "Apply source filters"
                                            onClicked: {
                                                const filters = [
                                                    {id: "local-color", kind: "color-correction", enabled: true,
                                                     amount: filterBrightness.value, value: ""},
                                                    {id: "local-opacity", kind: "opacity", enabled: true,
                                                     amount: filterOpacity.value, value: ""}
                                                ]
                                                if (filterScale.text.length > 0)
                                                    filters.push({id: "local-scale", kind: "scaling", enabled: true,
                                                                  amount: 1, value: filterScale.text})
                                                if (filterMask.text.length > 0)
                                                    filters.push({id: "local-mask", kind: "mask-blend", enabled: true,
                                                                  amount: 1, value: filterMask.text})
                                                if (!clientController.studio.preview.setItemFilters(
                                                        previewCanvas.selectedRow, filters)) {
                                                    errorBanner.color = "#9c2f37"
                                                    errorBanner.text = "Filter values were rejected by the bounded Scene contract."
                                                    errorBanner.visible = true
                                                }
                                            }
                                        }
                                        GridLayout {
                                            columns: 2
                                            Label { text: "Crop top" }
                                            SpinBox { id: cropTop; from: 0; to: 8192 }
                                            Label { text: "Crop right" }
                                            SpinBox { id: cropRight; from: 0; to: 8192 }
                                            Label { text: "Crop bottom" }
                                            SpinBox { id: cropBottom; from: 0; to: 8192 }
                                            Label { text: "Crop left" }
                                            SpinBox { id: cropLeft; from: 0; to: 8192 }
                                        }
                                        Button {
                                            text: "Apply crop"
                                            onClicked: clientController.studio.preview.setItemCrop(previewCanvas.selectedRow,
                                                cropTop.value, cropRight.value, cropBottom.value, cropLeft.value)
                                        }
                                        RowLayout {
                                            Button { text: "Left"; onClicked: clientController.studio.preview.alignItem(previewCanvas.selectedRow, "left", "") }
                                            Button { text: "Center"; onClicked: clientController.studio.preview.alignItem(previewCanvas.selectedRow, "center", "center") }
                                            Button { text: "Right"; onClicked: clientController.studio.preview.alignItem(previewCanvas.selectedRow, "right", "") }
                                        }
                                        Button { text: "Delete selected"; onClicked: clientController.studio.preview.removeItem(previewCanvas.selectedRow) }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
