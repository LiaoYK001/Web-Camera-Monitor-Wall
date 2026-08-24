import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: window
    width: 1280
    height: 800
    visible: true
    color: "#0b0f15"
    title: "WebObs Native — True Direct"
    property bool monitorFullscreen: false

    function enterMonitorFullscreen() {
        monitorFullscreen = true
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
        function onUserError(message) { errorBanner.text = message; errorBanner.visible = true }
    }

    header: ToolBar {
        visible: !window.monitorFullscreen
        RowLayout {
            anchors.fill: parent
            Label { text: "WebObs Native"; font.bold: true; Layout.leftMargin: 12 }
            Item { Layout.fillWidth: true }
            Label { text: clientController.liveTopology + " / archive: " + clientController.archiveTopology }
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
        height: 48
        radius: 6
        color: "#9c2f37"
        property alias text: errorText.text
        Text { id: errorText; anchors.centerIn: parent; color: "white" }
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
                TextField { id: deviceName; placeholderText: "Device name"; text: Qt.platform.os + " monitor"; Layout.fillWidth: true }
                Label { text: "Secure storage: " + clientController.storageBackend }
                Label { visible: clientController.temporaryIdentity; color: "#ffbf69";
                        text: "Secure storage unavailable: this session will not survive an app restart."; wrapMode: Text.Wrap }
                Button {
                    text: "Request pairing code"
                    enabled: server.text.length > 0 && deviceName.text.length > 0
                    onClicked: { clientController.serverUrl = server.text; clientController.enroll(deviceName.text) }
                }
                Label { visible: clientController.pairingCode.length === 8; text: clientController.pairingCode;
                        font.pixelSize: 42; font.letterSpacing: 5; Layout.alignment: Qt.AlignHCenter }
                Label { text: clientController.statusText; wrapMode: Text.Wrap; Layout.fillWidth: true }
            }
        }

        Item {
            RowLayout {
                anchors.fill: parent
                spacing: 0
                Pane {
                    visible: !window.monitorFullscreen
                    Layout.preferredWidth: 300
                    Layout.fillHeight: true
                    ColumnLayout {
                        anchors.fill: parent
                        Label { text: "Granted cameras"; font.bold: true }
                        ListView {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            model: clientController.cameras
                            delegate: ItemDelegate {
                                required property var modelData
                                width: ListView.view.width
                                text: modelData.name
                                onClicked: if (modelData.profiles.length > 0)
                                    clientController.startCamera(modelData.cameraId, modelData.profiles[0].id, "auto")
                            }
                        }
                        Label { text: "Decoder: " + clientController.media.decoder }
                        Label { color: clientController.media.hardwareDecode ? "#55d88a" : "#ffbf69";
                                text: clientController.media.hardwareDecode ? "Hardware decode" : "Software fallback" }
                        Label { text: clientController.fallbackReason; wrapMode: Text.Wrap; Layout.fillWidth: true }
                    }
                }
                Item {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    MonitorTile {
                        id: monitor
                        anchors.fill: parent
                        title: clientController.liveTopology.toUpperCase()
                        Component.onCompleted: clientController.attachVideoItem(videoItem)
                    }
                    Button {
                        visible: window.monitorFullscreen
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.margins: 16
                        text: "Exit fullscreen"
                        onClicked: window.leaveMonitorFullscreen()
                    }
                }
            }
        }
    }
}
