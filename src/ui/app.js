// SSHlyth - DSM 7 native app wrapper
// Opens the Flask SSH backend via the current DSM origin (preserves external port)

Ext.ns('SYNO.SDS.sshlyth');

Ext.define('SYNO.SDS.sshlyth.Instance', {
    extend: 'SYNO.SDS.AppInstance',
    appWindowName: 'SYNO.SDS.sshlyth.MainWindow',
    singleAppInstance: true,
    constructor: function (config) {
        this.callParent(arguments);
    }
});

Ext.define('SYNO.SDS.sshlyth.MainWindow', {
    extend: 'SYNO.SDS.AppWindow',
    appInstance: null,

    constructor: function (config) {
        Ext.apply(this, {
            title: 'SSHlyth Client',
            width: 960,
            height: 640,
            minWidth: 600,
            minHeight: 400,
            layout: 'fit',
            resizable: true,
            maximizable: true,
            minimizable: true
        });
        this.callParent(arguments);
    },

    initComponent: function () {
        // Use window.location.origin so the port from the browser URL is preserved
        // (e.g. http://nas.example.com:8080/SSHlyth/ instead of dropping the port)
        var appUrl = window.location.origin + '/SSHlyth/';
        this.items = [{
            xtype: 'component',
            autoEl: {
                tag: 'iframe',
                src: appUrl,
                frameBorder: 0,
                style: 'width:100%;height:100%;border:none;display:block;'
            }
        }];
        this.callParent(arguments);
    }
});
